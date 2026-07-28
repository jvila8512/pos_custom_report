from odoo import api, models

class PosSessionReport(models.AbstractModel):
    _name = 'report.pos_custom_report.pos_session_report'
    _description = 'POS Session Custom Report'

    @api.model
    def _get_report_values(self, docids, data=None):
        return {
            'doc_ids': docids,
            'doc_model': 'pos.session',
            'docs': self.env['pos.session'].browse(docids),
        }