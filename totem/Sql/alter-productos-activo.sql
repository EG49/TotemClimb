-- ============================================================
-- ALTER: productos.activo
-- ============================================================
-- Un producto que deja de venderse no se puede borrar, porque
-- detalle_factura lo referencia y las facturas antiguas deben
-- seguir mostrando qué se vendió. Se desactiva: desaparece de la
-- lista al cobrar, pero el historial queda intacto.
-- planes_membresia ya tenía esta columna; productos no.

ALTER TABLE productos
    ADD COLUMN activo BOOLEAN NOT NULL DEFAULT TRUE;
