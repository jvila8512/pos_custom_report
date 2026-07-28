/** @odoo-module */

import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/store/pos_store";
import { Order } from "@point_of_sale/app/store/models";
import { ErrorPopup } from "@point_of_sale/app/errors/popups/error_popup";
import { _t } from "@web/core/l10n/translation";

/**
 * Validacion de stock: no permitir vender productos sin stock.
 * Cubre dos caminos:
 *   1. Click en producto -> addProductToCurrentOrder -> addProductFromUi -> order.add_product
 *   2. Barcode -> _barcodeProductAction -> order.add_product (directo)
 */

// Funcion comun de validacion de stock
async function validateStock(pos, product, options) {
    if (!product || (product.type !== "product" && product.type !== "consu")) {
        return true; // servicios pasan sin validar
    }

    let availableQty = product.qty_available || 0;

    // Consultar stock en tiempo real al backend
    try {
        const stockData = await pos.orm.read(
            "product.product",
            [product.id],
            ["qty_available"]
        );
        if (stockData && stockData.length > 0) {
            availableQty = stockData[0].qty_available;
        }
    } catch (_error) {
        // Si falla, usar valor cacheado
    }

    // Restar lo ya vendido en la orden actual
    const order = pos.get_order();
    if (order) {
        const lines = order.get_orderlines();
        let soldInSession = 0;
        for (const line of lines) {
            if (line.product.id === product.id) {
                soldInSession += line.get_quantity();
            }
        }
        availableQty -= soldInSession;
    }

    const requestedQty = (options && options.quantity) || 1;

    if (availableQty <= 0) {
        await pos.popup.add(ErrorPopup, {
            title: _t("Sin stock"),
            body: _t('"${productName}" no tiene stock disponible.', {
                productName: product.display_name || product.name,
            }),
        });
        return false;
    }

    if (requestedQty > availableQty) {
        await pos.popup.add(ErrorPopup, {
            title: _t("Stock insuficiente"),
            body: _t(
                '"${productName}" solo tiene ${qty} unidades disponibles. Intento agregar ${requested}.',
                {
                    productName: product.display_name || product.name,
                    qty: availableQty,
                    requested: requestedQty,
                }
            ),
        });
        return false;
    }

    return true;
}

// Patch 1: Cubrir click en producto (camino principal)
patch(PosStore.prototype, {
    async addProductToCurrentOrder(product, options = {}) {
        if (Number.isInteger(product)) {
            product = this.db.get_product_by_id(product);
        }

        const allowed = await validateStock(this, product, options);
        if (!allowed) {
            return;
        }

        return super.addProductToCurrentOrder(...arguments);
    },
});

// Patch 2: Cubrir barcode y GS1 (camino directo)
patch(Order.prototype, {
    async add_product(product, options) {
        const allowed = await validateStock(this.pos, product, options);
        if (!allowed) {
            return;
        }

        return super.add_product(...arguments);
    },
});
