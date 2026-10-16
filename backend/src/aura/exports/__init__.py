"""Deal exports: render a DealExportBundle (aura.core.services.deal_export) to a file.

An adapter package: it depends on core, never the other way round."""
from aura.core.domain.export import DealExportBundle, ExportTable
from aura.exports.common import RenderedExport, deal_filename, list_filename

DEAL_FORMATS = ("pdf", "docx", "xlsx", "json", "zip")
LIST_FORMATS = ("csv", "xlsx")


def render_deal(bundle: DealExportBundle, fmt: str) -> RenderedExport:
    if fmt == "pdf":
        from aura.exports.pdf import render_pdf
        return render_pdf(bundle)
    if fmt == "docx":
        from aura.exports.docx_renderer import render_docx
        return render_docx(bundle)
    from aura.exports import tabular
    if fmt == "xlsx":
        return tabular.render_xlsx(bundle)
    if fmt == "json":
        return tabular.render_json(bundle)
    if fmt == "zip":
        return tabular.render_zip(bundle)
    raise ValueError(f"unknown deal export format {fmt!r}")


def render_list(table: ExportTable, fmt: str, generated_at: str,
                generated_by: str) -> RenderedExport:
    from aura.exports import tabular
    if fmt == "csv":
        return tabular.render_csv_table(table)
    if fmt == "xlsx":
        return tabular.render_list_xlsx(table, generated_at, generated_by)
    raise ValueError(f"unknown deals list export format {fmt!r}")


__all__ = ["DEAL_FORMATS", "LIST_FORMATS", "RenderedExport", "deal_filename", "list_filename",
           "render_deal", "render_list"]
