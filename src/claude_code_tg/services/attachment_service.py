"""附件管理服务。

提供附件清理和保留期管理功能。
"""

import logging
from pathlib import Path

from claude_code_tg.attachments import (
    PROJECT_ATTACHMENT_DIRNAME,
    prune_attachment_tree,
)

logger = logging.getLogger(__name__)


class AttachmentService:
    """附件管理服务。

    负责：
    - 管理附件存储根目录
    - 执行自动保留期清理
    """

    def __init__(
        self,
        attachment_dir: Path,
        project_dir: str,
        retention_days: float | None = None,
    ) -> None:
        """初始化附件服务。

        Args:
            attachment_dir: 实例附件目录
            project_dir: 项目工作目录
            retention_days: 保留天数（None 表示禁用自动清理）
        """
        self.attachment_dir = attachment_dir
        self.project_dir = project_dir
        self.retention_days = retention_days

    def cleanup_roots(self) -> list[tuple[str, Path]]:
        """返回需要清理的根目录列表。

        Returns:
            list[tuple[str, Path]]: (标签, 路径) 列表，已去重
        """
        roots = [
            ("instance", self.attachment_dir),
            (
                "project",
                Path(self.project_dir).expanduser().resolve(strict=False)
                / PROJECT_ATTACHMENT_DIRNAME,
            ),
        ]

        # 去重：相同的实际路径只保留一个
        seen: set[str] = set()
        unique_roots: list[tuple[str, Path]] = []
        for label, root in roots:
            root_key = str(root.expanduser().resolve(strict=False))
            if root_key in seen:
                continue
            seen.add(root_key)
            unique_roots.append((label, root))
        return unique_roots

    def run_retention_cleanup(self) -> tuple[int, int, int]:
        """执行保留期清理。

        清理超过保留期的附件文件。

        Returns:
            tuple[int, int, int]: (清理文件数, 清理字节数, 错误数)
        """
        if self.retention_days is None:
            return (0, 0, 0)

        older_than_seconds = self.retention_days * 86400
        total_files = 0
        total_bytes = 0
        total_errors = 0

        for label, root in self.cleanup_roots():
            result = prune_attachment_tree(
                root,
                older_than_seconds=older_than_seconds,
                dry_run=False,
            )
            total_files += result.files
            total_bytes += result.byte_count
            total_errors += len(result.errors)

            # 记录错误
            for error in result.errors:
                logger.warning("Attachment cleanup warning | scope=%s %s", label, error)

            # 记录清理结果
            if result.root_exists and (result.files or result.dirs_removed):
                logger.info(
                    "Attachment cleanup | scope=%s files=%d bytes=%d dirs=%d",
                    label,
                    result.files,
                    result.byte_count,
                    result.dirs_removed,
                )

        if total_errors:
            logger.warning(
                "Attachment cleanup completed with %d warning(s)", total_errors
            )

        return (total_files, total_bytes, total_errors)
