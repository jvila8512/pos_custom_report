from odoo import api, models, fields
from odoo.osv.expression import AND
from datetime import timedelta
import pytz

class SaleDetailsReport(models.AbstractModel):
    _inherit = "report.point_of_sale.report_saledetails"

    @api.model
    def _get_report_values(self, docids, data=None):
        """Sobreescribir para pasar supplier_ids al metodo get_sale_details."""
        data = dict(data or {})
        data.update({
            'session_ids': data.get('session_ids') or (
                docids if not data.get('config_ids') and not data.get('date_start') and not data.get('date_stop') else None
            ),
            'config_ids': data.get('config_ids'),
            'date_start': data.get('date_start'),
            'date_stop': data.get('date_stop'),
            'supplier_ids': data.get('supplier_ids'),
        })
        configs = self.env['pos.config'].browse(data['config_ids'])
        data.update(self.get_sale_details(
            data['date_start'], data['date_stop'], configs.ids, data['session_ids'],
            supplier_ids=data.get('supplier_ids'),
        ))
        return data

    @api.model
    def _get_supplier_product_ids(self, supplier_ids):
        """Obtener IDs de productos que pertenecen a los proveedores seleccionados."""
        if not supplier_ids:
            return False
        supplier_infos = self.env['product.supplierinfo'].search([
            ('partner_id', 'in', supplier_ids)
        ])
        product_tmpl_ids = supplier_infos.mapped('product_tmpl_id').ids
        if not product_tmpl_ids:
            return []
        product_ids = self.env['product.product'].search([
            ('product_tmpl_id', 'in', product_tmpl_ids)
        ]).ids
        return product_ids

    @api.model
    def get_sale_details(self, date_start=False, date_stop=False, config_ids=False, session_ids=False, supplier_ids=False):
        result = super().get_sale_details(date_start, date_stop, config_ids, session_ids)

        # Obtener IDs de productos filtrados por proveedor
        supplier_product_ids = self._get_supplier_product_ids(supplier_ids) if supplier_ids else False

        # Aplicar filtro de proveedor al resultado base del reporte
        if supplier_product_ids is not False:
            if not supplier_product_ids:
                # No hay productos de esos proveedores — vaciar todo
                result['products'] = []
                result['refund_products'] = []
                result['products_info'] = {'total': 0, 'qty': 0}
                result['refund_info'] = {'total': 0, 'qty': 0}
            else:
                result['products'] = self._filter_categories_by_products(
                    result.get('products', []), supplier_product_ids
                )
                result['refund_products'] = self._filter_categories_by_products(
                    result.get('refund_products', []), supplier_product_ids
                )
                # Recalcular totales
                result['products_info'] = self._recalculate_info(result['products'])
                result['refund_info'] = self._recalculate_info(result['refund_products'])

        # Solo calcular ganancias si el usuario es administrador
        if not self.env.user.has_group('base.group_system'):
            return result

        domain = [('state', 'in', ['paid', 'invoiced', 'done'])]

        if session_ids:
            domain = AND([domain, [('session_id', 'in', session_ids)]])
        else:
            if date_start:
                date_start_dt = fields.Datetime.from_string(date_start)
            else:
                user_tz = pytz.timezone(self.env.context.get('tz') or self.env.user.tz or 'UTC')
                today = user_tz.localize(fields.Datetime.from_string(fields.Date.context_today(self)))
                date_start_dt = today.astimezone(pytz.timezone('UTC')).replace(tzinfo=None)

            if date_stop:
                date_stop_dt = fields.Datetime.from_string(date_stop)
                if date_stop_dt < date_start_dt:
                    date_stop_dt = date_start_dt + timedelta(days=1, seconds=-1)
            else:
                date_stop_dt = date_start_dt + timedelta(days=1, seconds=-1)

            domain = AND([domain,
                [('date_order', '>=', fields.Datetime.to_string(date_start_dt)),
                 ('date_order', '<=', fields.Datetime.to_string(date_stop_dt))]
            ])

        if config_ids:
            domain = AND([domain, [('config_id', 'in', config_ids)]])

        orders = self.env['pos.order'].search(domain)

        # Guardar supplier_product_ids para usar en profit_data
        profit_data = self._calculate_profit_data(orders, supplier_product_ids)

        # Nombres de proveedores seleccionados para mostrar en el reporte
        supplier_names = []
        if supplier_ids:
            suppliers = self.env['res.partner'].browse(supplier_ids)
            supplier_names = suppliers.mapped('name')

        result['has_profit_analysis'] = True
        result['profit_data'] = profit_data
        result['supplier_filter_names'] = supplier_names
        return result

    def _filter_categories_by_products(self, categories, supplier_product_ids):
        """Filtrar categorias del reporte para incluir solo productos de los proveedores."""
        filtered = []
        for category in categories:
            filtered_products = [
                p for p in category.get('products', [])
                if p.get('product_id') in supplier_product_ids
            ]
            if filtered_products:
                filtered.append({
                    'name': category['name'],
                    'products': filtered_products,
                })
        return filtered

    def _recalculate_info(self, categories):
        """Recalcular totales despues de filtrar."""
        all_qty = 0
        all_total = 0
        for category in categories:
            for product in category.get('products', []):
                all_qty += product.get('quantity', 0)
                all_total += product.get('base_amount', 0)
        return {'total': all_total, 'qty': all_qty}

    def _calculate_profit_data(self, orders, supplier_product_ids=False):
        """Calcular datos de rentabilidad usando precio sin IVA y costo FIFO real.
        Si supplier_product_ids es una lista, solo incluye productos de esos IDs."""
        products_profit = {}
        total_cost = 0.0
        total_sales = 0.0

        # Obtener IDs de sesión para calcular stock inicial
        session_ids = set()
        for order in orders:
            if order.session_id:
                session_ids.add(order.session_id.id)

        for order in orders:
            for line in order.lines:
                if line.qty > 0:
                    # Filtro por proveedor: saltar lineas de productos que no pertenecen a los proveedores seleccionados
                    if supplier_product_ids is not False and line.product_id.id not in supplier_product_ids:
                        continue
                    product = line.product_id
                    quantity = line.qty
                    sales_total = line.price_subtotal # Sin IVA

                    # Usar total_cost de la línea (calculado con FIFO por Odoo)
                    # Si no está calculado (ej: consumibles), usar standard_price como fallback
                    if line.is_total_cost_computed:
                        cost_total = line.total_cost
                    else:
                        cost_total = (product.standard_price or 0) * quantity

                    profit = sales_total - cost_total

                    if product.id not in products_profit:
                        # Stock actual del producto
                        stock_current = product.qty_available or 0
                        # Stock inicial = stock actual + cantidad vendida en las sesiones del reporte
                        # (porque Odoo aún no descontó el stock de la sesión abierta)
                        products_profit[product.id] = {
                            'product_id': product.id,
                            'name': product.name,
                            'quantity': 0,
                            'cost_total': 0.0,
                            'sales_total': 0.0,
                            'profit': 0.0,
                            'is_fifo': product.cost_method == 'fifo',
                            'stock_current': stock_current,
                        }

                    products_profit[product.id]['quantity'] += quantity
                    products_profit[product.id]['cost_total'] += cost_total
                    products_profit[product.id]['sales_total'] += sales_total
                    products_profit[product.id]['profit'] += profit

                    total_cost += cost_total
                    total_sales += sales_total

        # Recalcular margen por producto y stock inicial
        for product_data in products_profit.values():
            if product_data['sales_total'] > 0:
                product_data['margin'] = (product_data['profit'] / product_data['sales_total'] * 100)
            else:
                product_data['margin'] = 0
            # Stock inicial = stock actual + vendido en esta sesión
            product_data['stock_initial'] = product_data['stock_current'] + product_data['quantity']

        total_profit = total_sales - total_cost
        profit_margin = (total_profit / total_sales * 100) if total_sales > 0 else 0

        products_list = sorted(products_profit.values(), key=lambda x: x['profit'], reverse=True)

        # Calcular participación sobre ganancia total
        for product_data in products_list:
            if total_profit > 0:
                product_data['profit_share'] = (product_data['profit'] / total_profit) * 100
            else:
                product_data['profit_share'] = 0

        return {
            'products': products_list[:100],
            'total_cost': total_cost,
            'total_sales': total_sales,
            'total_profit': total_profit,
            'profit_margin': profit_margin,
            'total_products_analyzed': len(products_list)
        }
