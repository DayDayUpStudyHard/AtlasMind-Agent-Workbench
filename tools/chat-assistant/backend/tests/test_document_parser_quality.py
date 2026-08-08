import unittest
from pathlib import Path
from unittest.mock import patch

from app.services.document_parser import DocumentParser, assess_extracted_text_quality
from app.services.document_parser_types import ParsedBlock


class DocumentParserQualityTest(unittest.TestCase):
    def test_marks_empty_pdf_text_as_low_quality(self):
        result = assess_extracted_text_quality("")

        self.assertEqual("LOW", result["level"])
        self.assertTrue(result["requiresOcr"])
        self.assertTrue(any(item["type"] == "EMPTY_TEXT" for item in result["signals"]))

    def test_marks_garbled_pdf_text_as_low_quality(self):
        result = assess_extracted_text_quality(
            "9. :l 履约 1呆民:乙方在合同签订 10 日之内，应向 IFl方提交保雨。"
            "逾期超过 :\\0 天，叩方可暂停履行。"
        )

        self.assertEqual("LOW", result["level"])
        self.assertTrue(result["requiresOcr"])
        self.assertGreater(len(result["signals"]), 0)

    def test_marks_glyph_soup_as_low_quality(self):
        sample = (
            "\u3014\u63d0 til1lf)\u6c11\u4e3b\u65e5\u79df\u4e16 \u00eciI\u6210\u5305\u5546"
            "\u5177\u6709\u63d0\u4f9b\u8be5\u8d44\u6296\u80fd\u529b\u4e4b\u65e5"
            " \u7684\u540e\u8005\u5f00\u59cb\u8ba1\u7b97\u3009\u4e4b\u5185\u65e0\u507f"
            " !Jt\u4f9b. 4 \u8bbe\u8ba1\u627f\u5305\u5546\u4eba\u5458"
        )
        result = assess_extracted_text_quality(sample)

        self.assertEqual("LOW", result["level"])
        self.assertTrue(result["requiresOcr"])
        self.assertTrue(any(item["type"] == "LOW_CJK_RATIO" for item in result["signals"]))

    def test_keeps_clean_contract_text(self):
        result = assess_extracted_text_quality(
            "乙方应在合同生效后十五日内完成初步设计，并向甲方提交完整设计文件。"
        )

        self.assertEqual("HIGH", result["level"])
        self.assertFalse(result["requiresOcr"])

    def test_auto_reparses_low_quality_text_with_available_ocr(self):
        parser = DocumentParser()

        def fake_pdf_parser(path, progress_callback=None, parse_mode="OCR", force_ocr=False,
                            allow_disabled_ocr=False):
            if parse_mode == "FAST":
                yield ParsedBlock("9. :l 履约 1呆民:乙方在合同签订 10 日之内，应向 IFl方提交保雨。")
            else:
                yield ParsedBlock("乙方应在合同签订后10日内提交完整履约保函，并完成项目实施方案。")

        with patch.object(parser, "_iter_pdf", side_effect=fake_pdf_parser), \
             patch("app.services.document_parser._ocr_runtime_available", return_value=True), \
             patch("app.services.document_parser.settings.ocr_enabled", False), \
             patch("app.services.document_parser.settings.mineru_enabled", False), \
             patch("app.services.document_parser.settings.pdf_auto_reparse", True):
            blocks = list(parser._iter_pdf_auto(Path("contract.pdf")))

        self.assertEqual("OCR", parser.last_diagnostics["provider"])
        self.assertTrue(parser.last_diagnostics["qualityEscalated"])
        self.assertIn("完整履约保函", blocks[0].text)

    def test_auto_reparses_empty_fast_pdf_with_available_ocr(self):
        parser = DocumentParser()

        def fake_pdf_parser(path, progress_callback=None, parse_mode="OCR", force_ocr=False,
                            allow_disabled_ocr=False, ocr_page_filter=None):
            if parse_mode == "FAST":
                return
            yield ParsedBlock(
                "\u4e59\u65b9\u5e94\u5728\u5408\u540c\u751f\u6548\u540e"
                "\u5341\u4e94\u65e5\u5185\u63d0\u4ea4\u5b8c\u6574"
                "\u8bbe\u8ba1\u6587\u4ef6\u3002",
                source_page=1,
            )

        with patch.object(parser, "_iter_pdf", side_effect=fake_pdf_parser), \
             patch("app.services.document_parser._ocr_runtime_available", return_value=True), \
             patch("app.services.document_parser.settings.ocr_enabled", False), \
             patch("app.services.document_parser.settings.mineru_enabled", False), \
             patch("app.services.document_parser.settings.pdf_auto_reparse", True):
            blocks = list(parser._iter_pdf_auto(Path("scanned-contract.pdf")))

        self.assertEqual("OCR", parser.last_diagnostics["provider"])
        self.assertTrue(parser.last_diagnostics["qualityEscalated"])
        self.assertEqual("all", parser.last_diagnostics["attempts"][-1]["pages"])
        self.assertEqual(
            "\u4e59\u65b9\u5e94\u5728\u5408\u540c\u751f\u6548\u540e"
            "\u5341\u4e94\u65e5\u5185\u63d0\u4ea4\u5b8c\u6574"
            "\u8bbe\u8ba1\u6587\u4ef6\u3002",
            blocks[0].text,
        )

    def test_auto_reparse_records_provider_unavailable_without_hiding_text(self):
        parser = DocumentParser()

        def fake_pdf_parser(path, progress_callback=None, parse_mode="OCR", force_ocr=False,
                            allow_disabled_ocr=False):
            yield ParsedBlock("9. :l 履约 1呆民:乙方在合同签订 10 日之内，应向 IFl方提交保雨。")

        with patch.object(parser, "_iter_pdf", side_effect=fake_pdf_parser), \
             patch("app.services.document_parser._ocr_runtime_available", return_value=False), \
             patch("app.services.document_parser._mineru_runtime_available", return_value=False), \
             patch("app.services.document_parser.settings.pdf_auto_reparse", True):
            blocks = list(parser._iter_pdf_auto(Path("contract.pdf")))

        self.assertEqual("FAST", parser.last_diagnostics["provider"])
        self.assertEqual("UNAVAILABLE", parser.last_diagnostics["qualityEscalationStatus"])
        self.assertTrue(blocks)
        self.assertTrue(parser.last_diagnostics["requiresReparse"])


if __name__ == "__main__":
    unittest.main()
