from odoo import http
from odoo.http import request

class ReportController(http.Controller):

    @http.route('/point_of_sale/get_profit_data', type='json', auth='user')
    def get_profit_data(self, session_id):
        """Endpoint para obtener datos de ganancias"""
        session = request.env['pos.session'].browse(session_id)
        return session.get_profit_data()