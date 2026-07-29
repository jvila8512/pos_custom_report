from odoo import fields, models


class PosExcelReportWizard(models.TransientModel):
    _name = 'pos.excel.report.wizard'
    _description = 'Wizard para reporte Excel de ventas POS'

    session_id = fields.Many2one('pos.session', string='Sesion')
    date_start = fields.Date(string='Fecha Inicio')
    date_stop = fields.Date(string='Fecha Fin')
    supplier_ids = fields.Many2many(
        'res.partner',
        string='Proveedores',
        help='Filtrar productos por proveedor.',
    )

    def generate_report(self):
        """Descargar reporte Excel con filtro de fechas y proveedor"""
        self.ensure_one()
        params = []

        if self.session_id:
            params.append('session_id=%s' % self.session_id.id)
        if self.date_start:
            params.append('date_start=%s' % self.date_start.strftime('%Y-%m-%d'))
        if self.date_stop:
            params.append('date_stop=%s' % self.date_stop.strftime('%Y-%m-%d'))
        if self.supplier_ids:
            params.append('supplier_ids=%s' % ','.join(str(sid) for sid in self.supplier_ids.ids))

        url = '/pos/sales_report_excel?%s' % '&'.join(params)
        return {
            'type': 'ir.actions.act_url',
            'url': url,
            'target': 'self',
        }
