/** @odoo-module */

import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/store/pos_store";
import { Order, Orderline } from "@point_of_sale/app/store/models";
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
    const productType = product && (product.type || product.detailed_type);
    if (!product || productType === "service" || productType === "combo") {
        return true; // servicios y combos pasan sin validar
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
            // Refrescar el cache del producto para que la guardia sincrona de
            // set_quantity (edicion de cantidad) use el stock real recien leido.
            product.qty_available = availableQty;
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
    const displayName = product.display_name || product.name;

    if (availableQty <= 0) {
        await pos.popup.add(ErrorPopup, {
            title: _t("Sin stock"),
            body: '"' + displayName + '" no tiene stock disponible.',
        });
        return false;
    }

    if (requestedQty > availableQty) {
        await pos.popup.add(ErrorPopup, {
            title: _t("Stock insuficiente"),
            body: '"' + displayName + '" solo tiene ' + availableQty + ' unidades disponibles. Intento agregar ' + requestedQty + '.',
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

// ---------------------------------------------------------------------------
// Patch 3: cubrir la EDICION de cantidad de una linea ya existente.
// Caminos que NO pasan por add_product:
//   - numpad: product_screen._setValue -> selectedLine.set_quantity(val)
//   - popup "Set the new quantity": updateQuantityNumber -> set_quantity
//   - botones +/- de la linea
// set_quantity es sincrono, asi que se valida contra el stock cacheado del
// producto menos lo ya vendido en TODAS las ordenes de la sesion.
// ---------------------------------------------------------------------------

function isStockProduct(product) {
    if (!product) {
        return false;
    }
    const productType = product.type || product.detailed_type;
    return productType !== "service" && productType !== "combo";
}

/**
 * Stock que le queda disponible a una linea, descontando lo que ya esta
 * cargado en otras lineas de la sesion (la cantidad de esta linea se excluye
 * porque va a ser reemplazada por la nueva).
 * Devuelve null si no hay dato de stock (para no bloquear por falta de info).
 */
function remainingStockForLine(line) {
    const product = line.product;
    const cached = product.qty_available;
    if (cached === undefined || cached === null) {
        return null;
    }

    let usedElsewhere = 0;
    const pos = line.pos;
    if (pos && pos.orders) {
        for (const order of pos.orders) {
            for (const other of order.orderlines || []) {
                if (other === line) {
                    continue;
                }
                if (!other.product || other.product.id !== product.id) {
                    continue;
                }
                if (other.refunded_orderline_id) {
                    continue; // las devoluciones no consumen stock
                }
                usedElsewhere += other.get_quantity();
            }
        }
    }
    return cached - usedElsewhere;
}

patch(Orderline.prototype, {
    set_quantity(quantity, keep_price) {
        const order = this.order;
        // Solo ediciones en vivo: la linea ya pertenece a la orden.
        // La carga inicial (constructor / init_from_JSON) queda sin validar
        // para no romper la reanudacion de sesiones con ordenes guardadas.
        const isLiveEdit = !!(order && order.orderlines && order.orderlines.includes(this));

        if (
            !isLiveEdit ||
            !isStockProduct(this.product) ||
            this.refunded_orderline_id ||
            this.comboParent
        ) {
            return super.set_quantity(...arguments);
        }

        const qty = typeof quantity === "number" ? quantity : parseFloat(quantity);
        if (!isFinite(qty) || qty <= 0) {
            return super.set_quantity(...arguments);
        }

        const remaining = remainingStockForLine(this);
        if (remaining === null) {
            return super.set_quantity(...arguments);
        }

        if (qty > remaining + 1e-6) {
            const displayName = this.product.display_name || this.product.name;
            const available = Math.max(remaining, 0);
            this.env.services.popup.add(ErrorPopup, {
                title: _t("Stock insuficiente"),
                body:
                    '"' +
                    displayName +
                    '" solo tiene ' +
                    available +
                    " unidades disponibles. Intento poner " +
                    qty +
                    ".",
            });
            return false;
        }

        return super.set_quantity(...arguments);
    },
});
