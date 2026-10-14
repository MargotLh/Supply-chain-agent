%dw 2.0

// ERP (SAP-style fields) <-> canonical model.
// Same mapping as the Python stand-in in integration/api.py: if the ERP changes,
// only this file changes; the agents keep seeing the canonical names.

fun order(o) = {
    order_id: o.ORD_NO,
    customer: { id: o.KUNNR, name: o.CUST_NAME, tier: o.CUST_TIER },
    sku: o.MATNR,
    description: o.MAKTX,
    quantity: o.MENGE,
    source_warehouse: o.WERKS,
    promised_date: o.PROMISED_DT,
    days_to_promise: daysBetween(o.SYSTEM_DATE as Date, o.PROMISED_DT as Date),
    order_value_gbp: o.NETWR_GBP,
    status: o.STATUS,
    actions: o.ACTIONS
}

fun inventory(s) = {
    sku: s.MATNR,
    locations: (s.ITEMS default []) map {
        warehouse_id: $.WERKS,
        warehouse_name: $.WERKS_NAME,
        available_units: $.LABST,
        reroute_cost_gbp: $.REROUTE_COST_GBP,
        transit_days: $.TRANSIT_D
    }
}

fun suppliers(v) = {
    sku: v.MATNR,
    suppliers: (v.ITEMS default []) map {
        supplier_id: $.LIFNR,
        supplier: $.NAME1,
        available_units: $.AVAIL_QTY,
        lead_time_days: $.LEAD_TIME_D,
        extra_cost: $.EXTRA_COST_GBP
    }
}

fun shipment(s) = {
    order_id: s.ORD_NO,
    shipment_id: s.TKNUM,
    carrier: s.CARRIER,
    original_eta: s.ORIG_ETA,
    current_eta: s.CURR_ETA,
    delay_reason: if (isEmpty(s.DELAY_RSN)) null else s.DELAY_RSN
}

fun events(raw) = {
    events: (raw.ITEMS default []) map {
        sequence: $.EVT_ID,
        "type": $.EVT_TYPE,
        order_id: $.ORD_NO,
        delay_days: $.DELAY_D,
        reason: $.RSN,
        occurred_at: $.TS,
        source: "ERP"
    }
}

// Canonical -> ERP, for writes.
fun erpAction(body, correlationId) = {
    ACTION: body.action,
    DETAIL: body.detail default "",
    EXTRA_COST_GBP: body.extra_cost_gbp default 0,
    APPROVAL_REF: body.approval_id,
    CORRELATION_ID: correlationId
}

fun erpMessage(body, correlationId) = {
    CHANNEL: body.channel default "ops-exceptions",
    TEXT: body.text,
    CORRELATION_ID: correlationId
}
