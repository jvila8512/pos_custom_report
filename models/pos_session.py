from odoo import models, fields, api
from collections import defaultdict
from datetime import datetime as dt


class PosSession(models.Model):
    _inherit = 'pos.session'

    def get_profit_data(self):
        """Obtener datos de ganancias usando precio sin IVA y costo FIFO real"""
        try:
            profit_data = {
                'products': [],
                'total_cost': 0,
                'total_sales': 0,
                'total_profit': 0,
                'profit_margin': 0
            }

            if not self.order_ids:
                return profit_data

            product_sales = defaultdict(lambda: {'qty': 0, 'sales': 0, 'cost': 0, 'is_fifo': False, 'stock_current': 0})

            for order in self.order_ids:
                for line in order.lines:
                    product = line.product_id
                    if product:
                        # Usar total_cost de la línea (calculado con FIFO por Odoo)
                        # Si no está calculado (ej: consumibles), usar standard_price como fallback
                        if line.is_total_cost_computed:
                            line_cost = line.total_cost
                        else:
                            cost_price = product.standard_price or 0
                            line_cost = cost_price * line.qty
                        line_sales = line.price_subtotal # Sin IVA

                        product_sales[product.id]['qty'] += line.qty
                        product_sales[product.id]['sales'] += line_sales
                        product_sales[product.id]['cost'] += line_cost
                        product_sales[product.id]['name'] = product.name
                        product_sales[product.id]['default_code'] = product.default_code or ''
                        product_sales[product.id]['is_fifo'] = product.cost_method == 'fifo'
                        product_sales[product.id]['stock_current'] = product.qty_available or 0

            # Primera pasada: calcular totales y margen por producto
            for product_id, data in product_sales.items():
                profit = data['sales'] - data['cost']
                margin = (profit / data['sales'] * 100) if data['sales'] > 0 else 0

                profit_data['total_cost'] += data['cost']
                profit_data['total_sales'] += data['sales']
                profit_data['total_profit'] += profit

                # Stock inicial = stock actual + vendido en esta sesión
                stock_current = data.get('stock_current', 0)
                stock_initial = stock_current + data['qty']

                profit_data['products'].append({
                    'name': data['name'],
                    'code': data['default_code'],
                    'quantity': data['qty'],
                    'cost_total': data['cost'],
                    'sales_total': data['sales'],
                    'profit': profit,
                    'margin': margin,
                    'is_fifo': data.get('is_fifo', False),
                    'stock_initial': stock_initial,
                    'stock_current': stock_current,
                })

            # Margen general
            if profit_data['total_sales'] > 0:
                profit_data['profit_margin'] = (profit_data['total_profit'] / profit_data['total_sales']) * 100

            # Segunda pasada: calcular participación sobre ganancia total
            for product in profit_data['products']:
                if profit_data['total_profit'] > 0:
                    product['profit_share'] = (product['profit'] / profit_data['total_profit']) * 100
                else:
                    product['profit_share'] = 0

            # Ordenar por mayor ganancia
            profit_data['products'].sort(key=lambda x: x['profit'], reverse=True)

            return profit_data

        except Exception as e:
            import logging
            _logger = logging.getLogger(__name__)
            _logger.exception("Error en get_profit_data")
            return {
                'products': [],
                'total_cost': 0,
                'total_sales': 0,
                'total_profit': 0,
                'profit_margin': 0
            }

    @api.model
    def get_sales_excel_data(self, session=None, date_start=False, date_stop=False, supplier_ids=False):
        """Obtener datos para el reporte Excel de ventas.
        Puede buscar por sesion, por rango de fechas, o ambos.

        :param session: obj session (opcional)
        :param date_start: date object (opcional)
        :param date_stop: date object (opcional)
        :param supplier_ids: lista de IDs de proveedores (opcional)
        """
        from odoo.osv.expression import AND
        from datetime import timedelta

        # Obtener IDs de productos filtrados por proveedor
        supplier_product_ids = False
        if supplier_ids:
            supplier_infos = self.env['product.supplierinfo'].search([
                ('partner_id', 'in', supplier_ids)
            ])
            product_tmpl_ids = supplier_infos.mapped('product_tmpl_id').ids
            if product_tmpl_ids:
                supplier_product_ids = self.env['product.product'].search([
                    ('product_tmpl_id', 'in', product_tmpl_ids)
                ]).ids
            else:
                supplier_product_ids = []

        # Buscar ordenes
        domain = [('state', 'in', ['paid', 'invoiced', 'done'])]

        # Las fechas tienen prioridad. Si el usuario puso el rango de fechas,
        # se filtra SOLO por fechas (la sesion queda ignorada).
        if date_start or date_stop:
            if date_start:
                dt_start = dt.combine(date_start, dt.min.time())
                domain = AND([domain, [('date_order', '>=', fields.Datetime.to_string(dt_start))]])
            if date_stop:
                dt_stop = dt.combine(date_stop, dt.max.time())
                domain = AND([domain, [('date_order', '<=', fields.Datetime.to_string(dt_stop))]])
            session_name = 'Rango de fechas'
            if date_start and date_stop and date_start == date_stop:
                # Misma fecha -> mostrar solo una
                report_date = date_start.strftime('%d/%m/%Y')
            else:
                report_date = (
                    ('%s al %s' % (date_start.strftime('%d/%m/%Y'), date_stop.strftime('%d/%m/%Y')))
                    if date_start and date_stop
                    else (('Desde %s' % date_start.strftime('%d/%m/%Y')) if date_start else ('Hasta %s' % date_stop.strftime('%d/%m/%Y')))
                )
            currency_symbol = self.env.company.currency_id.symbol or '$'
        elif session:
            domain = AND([domain, [('session_id', '=', session.id)]])
            report_date = session.start_at.strftime('%d/%m/%Y %H:%M') if session.start_at else ''
            session_name = session.name or ''
            currency_symbol = session.currency_id.symbol or '$'
        else:
            report_date = ''
            session_name = ''
            currency_symbol = self.env.company.currency_id.symbol or '$'

        orders = self.env['pos.order'].search(domain)

        data = {
            'company_name': self.env.company.name,
            'report_date': report_date,
            'session_name': session_name,
            'currency_symbol': currency_symbol,
            'supplier_filter_names': [],
            'date_start': date_start.strftime('%d/%m/%Y') if date_start else '',
            'date_stop': date_stop.strftime('%d/%m/%Y') if date_stop else '',
            'products': [],
            'totals': {
                'stock_initial': 0,
                'qty_sold': 0,
                'stock_current': 0,
            },
        }

        # Agregar nombres de proveedores filtrados
        if supplier_ids:
            suppliers = self.env['res.partner'].browse(supplier_ids)
            data['supplier_filter_names'] = suppliers.mapped('name')

        if not orders:
            return data

        # Recopilar ventas por producto
        product_sales = defaultdict(lambda: {
            'qty': 0, 'name': '', 'standard_price': 0.0, 'stock_current': 0,
        })

        for order in orders:
            for line in order.lines:
                product = line.product_id
                if product:
                    # Filtro por proveedor
                    if supplier_product_ids is not False and product.id not in supplier_product_ids:
                        continue
                    product_sales[product.id]['qty'] += line.qty
                    product_sales[product.id]['name'] = product.name
                    product_sales[product.id]['standard_price'] = product.standard_price or 0
                    product_sales[product.id]['stock_current'] = product.qty_available or 0

        for product_id, pdata in product_sales.items():
            stock_current = pdata.get('stock_current', 0)
            qty_sold = pdata['qty']
            stock_initial = stock_current + qty_sold

            data['products'].append({
                'name': pdata['name'],
                'stock_initial': stock_initial,
                'stock_entry': 0,
                'qty_sold': qty_sold,
                'stock_current': stock_current,
                'cost': pdata.get('standard_price', 0),
            })

            data['totals']['stock_initial'] += stock_initial
            data['totals']['qty_sold'] += qty_sold
            data['totals']['stock_current'] += stock_current

        # Ordenar por nombre
        data['products'].sort(key=lambda x: x['name'])

        return data

    def action_download_sales_excel(self):
        """Abrir wizard para descargar reporte Excel con filtro de proveedor"""
        self.ensure_one()
        wizard = self.env['pos.excel.report.wizard'].create({
            'session_id': self.id,
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'pos.excel.report.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }
