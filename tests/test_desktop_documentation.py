"""Documentation contract for the Windows report-assessment workflow."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DesktopDocumentationTests(unittest.TestCase):
    def test_readme_and_manual_publish_the_complete_scope_and_safety_boundary(self) -> None:
        documents = {
            "README": (ROOT / "README.md").read_text(encoding="utf-8"),
            "manual": (ROOT / "docs" / "使用手册.md").read_text(encoding="utf-8"),
        }
        required = (
            "仅支持 Windows",
            "文字型 PDF",
            "扫描 PDF",
            "DOCX",
            "不支持 `.doc`",
            "本地文本提取 → 自动 OCR → 可选视觉模型兜底 → 大模型判断",
            "OpenAI 兼容接口",
            "Windows 凭据管理器",
            "Microsoft Visual C++ Runtime",
            "现行正式工作簿",
            "risk_id/name/domain/description",
            "不提供知识库、RAG、向量检索或报告问答",
            "人工确认",
            "不覆盖原工作簿",
            "虚构测试数据",
            "非生产",
        )
        for label, body in documents.items():
            with self.subTest(document=label):
                for phrase in required:
                    self.assertIn(phrase, body)

    def test_manual_explains_operations_privacy_and_risk_interpretation(self) -> None:
        manual = (ROOT / "docs" / "使用手册.md").read_text(encoding="utf-8")
        for phrase in (
            "四步流程",
            "测试连接",
            "重新选择报告",
            "模型输出只是建议",
            "历史审计发现不能单独证明当前剩余风险",
            "%LOCALAPPDATA%\\RiskAssessmentHeatMap",
            "删除本地任务",
            "正式真源",
            "--offline-verify",
        ):
            self.assertIn(phrase, manual)


if __name__ == "__main__":
    unittest.main()
