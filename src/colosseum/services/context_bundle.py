from __future__ import annotations

import base64
import binascii
import hashlib
import json
import mimetypes
from pathlib import Path
from typing import Any

from colosseum.core.config import MAX_CONTEXT_PROMPT_CHARS, PROMPT_BUDGET_TRUNCATION_MARKER
from colosseum.core.models import (
    ContextFragment,
    ContextSourceInput,
    ContextSourceKind,
    FrozenContextBundle,
    FrozenContextSource,
)


class ContextBundleService:
    def freeze(self, sources: list[ContextSourceInput]) -> FrozenContextBundle:
        frozen_sources = [self._freeze_source(source) for source in sources]
        aggregate_checksum = self._hash_text(
            json.dumps(
                [source.model_dump(mode="json") for source in frozen_sources],
                sort_keys=True,
            )
        )
        bundle_summary = self._build_bundle_summary(frozen_sources)
        return FrozenContextBundle(
            sources=frozen_sources,
            aggregate_checksum=aggregate_checksum,
            bundle_summary=bundle_summary,
        )

    def render_for_prompt(self, bundle: FrozenContextBundle, max_chars: int = MAX_CONTEXT_PROMPT_CHARS) -> str:
        base_sections: list[str] = [
            f"Bundle ID: {bundle.bundle_id}",
            f"Bundle checksum: {bundle.aggregate_checksum}",
            f"Summary: {bundle.bundle_summary}",
        ]
        sections: list[str] = []
        used_chars = 0
        total_fragments = sum(len(source.fragments) for source in bundle.sources)
        included_fragments = 0
        truncated_for_budget = False

        for section in base_sections:
            used_chars, appended = self._append_section(
                sections=sections,
                used_chars=used_chars,
                section=section,
                max_chars=max_chars,
            )
            if not appended:
                truncated_for_budget = True
                break
        for source in bundle.sources:
            source_lines = [f"Source {source.source_id} [{source.kind}]: {source.label}"]
            if source.description:
                source_lines.append(f"Description: {source.description}")
            if source.resolved_uri:
                source_lines.append(f"URI: {source.resolved_uri}")
            if source.metadata:
                source_lines.append(f"Metadata: {json.dumps(source.metadata, sort_keys=True)}")
            used_chars, appended = self._append_section(
                sections=sections,
                used_chars=used_chars,
                section="\n".join(source_lines),
                max_chars=max_chars,
            )
            if not appended:
                truncated_for_budget = True
                break
            for fragment in source.fragments:
                fragment_text = self._render_fragment_for_prompt(fragment)
                used_chars, appended = self._append_section(
                    sections=sections,
                    used_chars=used_chars,
                    section=fragment_text,
                    max_chars=max_chars,
                    allow_truncation=True,
                )
                if appended:
                    included_fragments += 1
                    continue
                truncated_for_budget = True
                break
            if truncated_for_budget:
                break

        if truncated_for_budget and included_fragments < total_fragments:
            omitted_fragments = total_fragments - included_fragments
            notice = (
                f"Prompt budget applied: included {included_fragments} of {total_fragments} "
                f"fragment(s); omitted {omitted_fragments} fragment(s) to control token usage."
            )
            self._append_section(
                sections=sections,
                used_chars=used_chars,
                section=notice,
                max_chars=max_chars,
                allow_truncation=True,
            )
        return "\n\n".join(sections)

    def extract_image_inputs(self, bundle: FrozenContextBundle) -> list[dict[str, Any]]:
        image_inputs: list[dict[str, Any]] = []
        for source in bundle.sources:
            for fragment in source.fragments:
                if not fragment.is_binary:
                    continue
                media_type = fragment.media_type or source.metadata.get("media_type", "")
                if not media_type.startswith("image/"):
                    continue
                image_inputs.append(
                    {
                        "source_id": source.source_id,
                        "label": fragment.label,
                        "path": fragment.path or source.resolved_path,
                        "media_type": media_type,
                        "checksum": fragment.checksum,
                        "size_bytes": fragment.size_bytes,
                        "inline_data": fragment.inline_data,
                    }
                )
        return image_inputs

    def summarize_image_inputs(self, bundle: FrozenContextBundle, limit: int = 4) -> str:
        image_inputs = self.extract_image_inputs(bundle)
        if not image_inputs:
            return "No shared image inputs."
        entries = []
        for item in image_inputs[:limit]:
            size_bytes = item.get("size_bytes") or 0
            size_text = f"{round(size_bytes / 1024, 1)} KB" if size_bytes else "size unknown"
            entries.append(
                f"{item['label']} ({item['media_type']}, {size_text}, checksum {str(item['checksum'])[:8]})"
            )
        remainder = len(image_inputs) - len(entries)
        if remainder > 0:
            entries.append(f"+{remainder} more image(s)")
        return f"{len(image_inputs)} shared image(s): " + "; ".join(entries)

    def _freeze_source(self, source: ContextSourceInput) -> FrozenContextSource:
        if source.kind == ContextSourceKind.INLINE_TEXT:
            content = source.content or ""
            return FrozenContextSource(
                source_id=source.source_id,
                kind=source.kind,
                label=source.label,
                description=source.description,
                checksum=self._hash_text(content),
                fragments=[
                    ContextFragment(
                        label=source.label,
                        content=content,
                        checksum=self._hash_text(content),
                    )
                ],
            )

        if source.kind == ContextSourceKind.INLINE_IMAGE:
            media_type, data_url, raw_bytes = self._decode_inline_image(
                source.content or "",
                source.media_type,
            )
            checksum = self._hash_bytes(raw_bytes)
            return FrozenContextSource(
                source_id=source.source_id,
                kind=source.kind,
                label=source.label,
                description=source.description,
                checksum=checksum,
                fragments=[
                    ContextFragment(
                        label=source.label,
                        content=self._binary_fragment_placeholder(media_type),
                        checksum=checksum,
                        media_type=media_type,
                        is_binary=True,
                        size_bytes=len(raw_bytes),
                        inline_data=data_url,
                    )
                ],
                metadata={
                    "media_type": media_type,
                    "size_bytes": len(raw_bytes),
                    "binary": True,
                },
            )

        if source.kind == ContextSourceKind.LOCAL_FILE:
            if not source.path:
                raise ValueError(f"Context source {source.source_id} is missing a path.")
            path = Path(source.path)
            content, truncated = self._read_text(path, source.max_chars)
            checksum = self._hash_text(content)
            return FrozenContextSource(
                source_id=source.source_id,
                kind=source.kind,
                label=source.label,
                description=source.description,
                resolved_path=str(path.resolve()),
                checksum=checksum,
                fragments=[
                    ContextFragment(
                        label=path.name,
                        path=str(path.resolve()),
                        content=content,
                        checksum=checksum,
                        truncated=truncated,
                    )
                ],
            )

        if source.kind == ContextSourceKind.LOCAL_IMAGE:
            if not source.path:
                raise ValueError(f"Context source {source.source_id} is missing a path.")
            path = Path(source.path)
            raw_bytes = path.read_bytes()
            media_type = self._infer_image_media_type(path, source.media_type)
            checksum = self._hash_bytes(raw_bytes)
            data_url = self._to_data_url(raw_bytes, media_type)
            resolved_path = str(path.resolve())
            return FrozenContextSource(
                source_id=source.source_id,
                kind=source.kind,
                label=source.label,
                description=source.description,
                resolved_path=resolved_path,
                checksum=checksum,
                fragments=[
                    ContextFragment(
                        label=path.name,
                        path=resolved_path,
                        content=self._binary_fragment_placeholder(media_type),
                        checksum=checksum,
                        media_type=media_type,
                        is_binary=True,
                        size_bytes=len(raw_bytes),
                        inline_data=data_url,
                    )
                ],
                metadata={
                    "media_type": media_type,
                    "size_bytes": len(raw_bytes),
                    "binary": True,
                },
            )

        if source.kind == ContextSourceKind.LOCAL_DIRECTORY:
            if not source.path:
                raise ValueError(f"Context source {source.source_id} is missing a path.")
            directory = Path(source.path)
            files = sorted(file for file in directory.rglob("*") if file.is_file())
            fragments: list[ContextFragment] = []
            file_checksums: list[str] = []
            for file in files[: source.max_files]:
                content, truncated = self._read_text(file, source.max_chars)
                checksum = self._hash_text(content)
                file_checksums.append(f"{file}:{checksum}")
                fragments.append(
                    ContextFragment(
                        label=file.name,
                        path=str(file.resolve()),
                        content=content,
                        checksum=checksum,
                        truncated=truncated,
                    )
                )
            checksum = self._hash_text("\n".join(file_checksums))
            return FrozenContextSource(
                source_id=source.source_id,
                kind=source.kind,
                label=source.label,
                description=source.description,
                resolved_path=str(directory.resolve()),
                checksum=checksum,
                fragments=fragments,
                metadata={"file_count": len(files), "included_files": len(fragments)},
            )

        if source.kind == ContextSourceKind.EXTERNAL_REFERENCE:
            uri = source.uri or source.content or ""
            checksum = self._hash_text(uri)
            note = (
                "External reference frozen as metadata only in the MVP. "
                "Fetch and snapshot content upstream for strict fairness."
            )
            return FrozenContextSource(
                source_id=source.source_id,
                kind=source.kind,
                label=source.label,
                description=source.description,
                resolved_uri=uri,
                checksum=checksum,
                fragments=[
                    ContextFragment(
                        label=source.label,
                        content=note,
                        checksum=self._hash_text(note),
                    )
                ],
            )

        raise ValueError(f"Unsupported source kind: {source.kind}")

    def _read_text(self, path: Path, max_chars: int) -> tuple[str, bool]:
        try:
            raw = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raw = path.read_text(encoding="utf-8", errors="ignore")
        truncated = len(raw) > max_chars
        if truncated:
            raw = f"{raw[:max_chars]}\n\n[TRUNCATED]"
        return raw, truncated

    def _build_bundle_summary(self, frozen_sources: list[FrozenContextSource]) -> str:
        parts = [f"{len(frozen_sources)} source(s) frozen"]
        for source in frozen_sources:
            fragment_count = len(source.fragments)
            image_note = ""
            if any(fragment.is_binary for fragment in source.fragments):
                image_note = ", visual context included"
            parts.append(
                f"{source.label}: {fragment_count} fragment(s), checksum {source.checksum[:8]}{image_note}"
            )
        return "; ".join(parts)

    def _hash_text(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _hash_bytes(self, payload: bytes) -> str:
        return hashlib.sha256(payload).hexdigest()

    def _render_fragment_for_prompt(self, fragment: ContextFragment) -> str:
        path_text = f" ({fragment.path})" if fragment.path else ""
        if fragment.is_binary:
            size_text = ""
            if fragment.size_bytes:
                size_text = f", {round(fragment.size_bytes / 1024, 1)} KB"
            media_type = fragment.media_type or "binary/octet-stream"
            return (
                f"Fragment: {fragment.label}{path_text}\n"
                f"[Binary attachment omitted from text prompt: {media_type}{size_text}. "
                "Use the shared multimodal context package instead.]"
            ).strip()
        return f"Fragment: {fragment.label}{path_text}\n{fragment.content}".strip()

    def _binary_fragment_placeholder(self, media_type: str) -> str:
        return (
            f"Binary attachment ({media_type}) frozen in the bundle. "
            "The raw data is preserved out-of-band for multimodal providers and excluded from text prompts."
        )

    def _decode_inline_image(self, content: str, hinted_media_type: str | None) -> tuple[str, str, bytes]:
        if not content:
            raise ValueError("Inline image source is missing content.")
        if content.startswith("data:"):
            header, encoded = content.split(",", 1)
            if ";base64" not in header:
                raise ValueError("Inline image content must be a base64 data URL.")
            media_type = header[5:].split(";", 1)[0] or hinted_media_type or "image/png"
            raw_bytes = self._decode_base64(encoded)
            self._ensure_image_media_type(media_type)
            return media_type, content, raw_bytes

        media_type = hinted_media_type or "image/png"
        self._ensure_image_media_type(media_type)
        raw_bytes = self._decode_base64(content)
        return media_type, self._to_data_url(raw_bytes, media_type), raw_bytes

    def _decode_base64(self, encoded: str) -> bytes:
        try:
            return base64.b64decode(encoded, validate=True)
        except binascii.Error as exc:
            raise ValueError("Image content is not valid base64.") from exc

    def _to_data_url(self, raw_bytes: bytes, media_type: str) -> str:
        encoded = base64.b64encode(raw_bytes).decode("ascii")
        return f"data:{media_type};base64,{encoded}"

    def _infer_image_media_type(self, path: Path, hinted_media_type: str | None) -> str:
        media_type = hinted_media_type or mimetypes.guess_type(path.name)[0] or "image/png"
        self._ensure_image_media_type(media_type)
        return media_type

    def _ensure_image_media_type(self, media_type: str) -> None:
        if not media_type.startswith("image/"):
            raise ValueError(f"Expected an image media type, received {media_type}.")

    def _append_section(
        self,
        sections: list[str],
        used_chars: int,
        section: str,
        max_chars: int,
        allow_truncation: bool = False,
    ) -> tuple[int, bool]:
        separator = "\n\n" if sections else ""
        available = max_chars - used_chars - len(separator)
        if available <= 0:
            return used_chars, False
        if len(section) <= available:
            sections.append(section)
            return used_chars + len(separator) + len(section), True
        if allow_truncation and available > len(PROMPT_BUDGET_TRUNCATION_MARKER) + 32:
            truncated = section[: available - len(PROMPT_BUDGET_TRUNCATION_MARKER)] + PROMPT_BUDGET_TRUNCATION_MARKER
            sections.append(truncated)
            return max_chars, False
        return used_chars, False
