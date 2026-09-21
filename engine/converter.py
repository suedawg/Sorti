"""
Microsoft Office COM PDF Converter for Sorti.
Automates native Microsoft Word and PowerPoint COM exports for 100% layout fidelity.
"""

from pathlib import Path
import os
import sys
from typing import Optional, Tuple

class OfficePdfConverter:
    def __init__(self):
        self.wdExportFormatPDF = 17
        self.ppSaveAsPDF = 32

    def convert_to_pdf(self, input_path: Path, output_pdf_path: Optional[Path] = None) -> Tuple[bool, Path, str]:
        """
        Converts a Word (.docx, .doc) or PowerPoint (.pptx, .ppt) file to a pristine PDF
        using native Microsoft Office COM automation.
        Returns (success, pdf_path, message).
        """
        input_path = Path(input_path).resolve()
        if not input_path.exists():
            return False, input_path, f"Input file not found: {input_path}"

        ext = input_path.suffix.lower()
        if ext not in ('.docx', '.doc', '.pptx', '.ppt'):
            # If already PDF or non-office format, return as is
            return True, input_path, "File does not require Office conversion."

        if output_pdf_path is None:
            output_pdf_path = input_path.with_suffix('.pdf')
        else:
            output_pdf_path = Path(output_pdf_path).resolve()

        output_pdf_path.parent.mkdir(parents=True, exist_ok=True)

        if ext in ('.docx', '.doc'):
            return self._convert_word(input_path, output_pdf_path)
        else:
            return self._convert_powerpoint(input_path, output_pdf_path)

    def _convert_word(self, input_path: Path, output_pdf_path: Path) -> Tuple[bool, Path, str]:
        word = None
        doc = None
        try:
            import pythoncom
            pythoncom.CoInitialize()
            import win32com.client

            word = win32com.client.DispatchEx("Word.Application")
            word.Visible = False
            word.DisplayAlerts = 0  # wdAlertsNone

            doc = word.Documents.Open(
                FileName=str(input_path),
                ConfirmConversions=False,
                ReadOnly=True,
                AddToRecentFiles=False
            )

            doc.ExportAsFixedFormat(
                OutputFileName=str(output_pdf_path),
                ExportFormat=self.wdExportFormatPDF,
                OpenAfterExport=False,
                OptimizeFor=0,    # wdExportOptimizeForPrint
                CreateBookmarks=1  # wdExportCreateHeadingBookmarks
            )

            doc.Close(SaveChanges=False)
            doc = None
            word.Quit()
            word = None

            return True, output_pdf_path, "Successfully converted Word document via Microsoft Word."

        except Exception as e:
            err_msg = str(e)
            print(f"[OfficePdfConverter] Word COM export error: {err_msg}")
            if doc:
                try:
                    doc.Close(SaveChanges=False)
                except Exception:
                    pass
            if word:
                try:
                    word.Quit()
                except Exception:
                    pass
            return False, input_path, f"Word COM error: {err_msg}"
        finally:
            try:
                import pythoncom
                pythoncom.CoUninitialize()
            except Exception:
                pass

    def _convert_powerpoint(self, input_path: Path, output_pdf_path: Path) -> Tuple[bool, Path, str]:
        powerpoint = None
        presentation = None
        try:
            import pythoncom
            pythoncom.CoInitialize()
            import win32com.client

            powerpoint = win32com.client.DispatchEx("PowerPoint.Application")
            # In PowerPoint COM, WithWindow=False runs headlessly
            presentation = powerpoint.Presentations.Open(
                FileName=str(input_path),
                ReadOnly=True,
                Untitled=False,
                WithWindow=False
            )

            # 32 = ppSaveAsPDF
            presentation.SaveAs(FileName=str(output_pdf_path), FileFormat=self.ppSaveAsPDF)

            presentation.Close()
            presentation = None
            powerpoint.Quit()
            powerpoint = None

            return True, output_pdf_path, "Successfully converted presentation via Microsoft PowerPoint."

        except Exception as e:
            err_msg = str(e)
            print(f"[OfficePdfConverter] PowerPoint COM export error: {err_msg}")
            if presentation:
                try:
                    presentation.Close()
                except Exception:
                    pass
            if powerpoint:
                try:
                    powerpoint.Quit()
                except Exception:
                    pass
            return False, input_path, f"PowerPoint COM error: {err_msg}"
        finally:
            try:
                import pythoncom
                pythoncom.CoUninitialize()
            except Exception:
                pass

# Backward compatibility alias
WordPdfConverter = OfficePdfConverter

