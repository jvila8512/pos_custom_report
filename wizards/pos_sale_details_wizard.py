from odoo import api, fields, models


class PosDetailsSupplier(models.TransientModel):
    _inherit = 'pos.details.wizard'

    supplier_ids = fields.Many2many(
        'res.partner',
        string='Proveedores',
        help='Filtrar productos por proveedor. Si se selecciona al menos un proveedor, solo se mostraran los productos de esos proveedores.',
    )

    def generate_report(self):
        data = {
            'date_start': self.start_date,
            'date_stop': self.end_date,
            'config_ids': self.pos_config_ids.ids,
            'supplier_ids': self.supplier_ids.ids,
        }
        return self.env.ref('point_of_sale.sale_details_report').report_action([], data=data)


class PosDailySalesReportSupplier(models.TransientModel):
    _inherit = 'pos.daily.sales.reports.wizard'

    supplier_ids = fields.Many2many(
        'res.partner',
        string='Proveedores',
        help='Filtrar productos por proveedor. Si se selecciona al menos un proveedor, solo se mostraran los productos de esos proveedores.',
    )

    def generate_report(self):
        data = {
            'date_start': False,
            'date_stop': False,
            'config_ids': self.pos_session_id.config_id.ids,
            'session_ids': self.pos_session_id.ids,
            'supplier_ids': self.supplier_ids.ids,
        }
        return self.env.ref('point_of_sale.sale_details_report').report_action([], data=data)
