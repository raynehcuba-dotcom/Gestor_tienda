-- ============================================================================
-- SISTEMA DE GESTIÓN DE INVENTARIO Y VENTAS: GESTOR TIENDA (MIPYME)
-- Motor: SQLite 3 (Modo WAL con Foreign Keys y Verificación Criptográfica)
-- Arquitectura: 100% Offline, Transaccional y Auditada
-- ============================================================================

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA encoding = 'UTF-8';

-- ----------------------------------------------------------------------------
-- 1. TABLA DE CONFIGURACIÓN Y PARÁMETROS DEL NEGOCIO
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS configuracion_negocio (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    nombre_tienda TEXT NOT NULL DEFAULT 'Gestor Tienda',
    razon_social TEXT NOT NULL DEFAULT 'Gestor Tienda S.R.L.',
    rut_fiscal TEXT DEFAULT '40019283741',
    direccion TEXT DEFAULT 'Calle Principal #102 e/ Central y Línea',
    telefono TEXT DEFAULT '+53 52000000',
    moneda_principal TEXT NOT NULL DEFAULT 'CUP',
    tasa_cambio_usd_cup REAL NOT NULL DEFAULT 320.00,
    tasa_cambio_mlc_cup REAL NOT NULL DEFAULT 270.00,
    fondo_fijo_caja_chica REAL NOT NULL DEFAULT 25000.00,
    tope_vale_caja_chica REAL NOT NULL DEFAULT 5000.00,
    margen_utilidad_default REAL NOT NULL DEFAULT 25.00,
    dias_alerta_caducidad INTEGER NOT NULL DEFAULT 90,
    version_db TEXT NOT NULL DEFAULT 'v1.0.0',
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ----------------------------------------------------------------------------
-- 2. USUARIOS, ROLES Y AUTENTICACIÓN LOCAL
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre_completo TEXT NOT NULL,
    username TEXT NOT NULL UNIQUE,
    pin_hash TEXT NOT NULL, -- SHA-256 del PIN numérico para TPV
    password_hash TEXT NOT NULL, -- PBKDF2/Bcrypt hash para acceso administrativo
    rol TEXT NOT NULL CHECK (rol IN ('admin', 'cajero', 'almacenero', 'auditor')),
    activo INTEGER NOT NULL DEFAULT 1,
    carnet_identidad TEXT,
    telefono TEXT,
    ultimo_acceso DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ----------------------------------------------------------------------------
-- 3. PROVEEDORES Y OBLIGACIONES COMERCIALES
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS proveedores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo_ref TEXT NOT NULL UNIQUE,
    nombre_comercial TEXT NOT NULL,
    razon_social TEXT,
    identificacion_fiscal TEXT,
    contacto_nombre TEXT,
    telefono TEXT,
    direccion TEXT,
    tipo_proveedor TEXT DEFAULT 'Consignación / Venta Devengada' CHECK (tipo_proveedor IN ('Consignación / Venta Devengada', 'Compra Firme', 'Mixto')),
    saldo_pendiente_efectivo REAL NOT NULL DEFAULT 0.00,
    saldo_pendiente_transferencia REAL NOT NULL DEFAULT 0.00,
    activo INTEGER NOT NULL DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ----------------------------------------------------------------------------
-- 4. CATEGORÍAS Y PRODUCTOS (CATÁLOGO Y STOCK)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS categorias (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL UNIQUE,
    descripcion TEXT,
    icono TEXT DEFAULT 'folder'
);

CREATE TABLE IF NOT EXISTS productos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku TEXT NOT NULL UNIQUE,
    codigo_barras TEXT UNIQUE,
    descripcion TEXT NOT NULL,
    categoria_id INTEGER NOT NULL REFERENCES categorias(id),
    proveedor_id INTEGER REFERENCES proveedores(id),
    unidad_medida TEXT NOT NULL DEFAULT 'UNIDAD' CHECK (unidad_medida IN ('UNIDAD', 'CAJA', 'PAQUETE', 'KG', 'LITRO', 'BULTO')),
    stock_actual REAL NOT NULL DEFAULT 0.0,
    stock_minimo REAL NOT NULL DEFAULT 10.0,
    costo_ultimo REAL NOT NULL DEFAULT 0.0,
    costo_pmp REAL NOT NULL DEFAULT 0.0, -- Precio Medio Ponderado
    precio_venta_cup REAL NOT NULL,
    precio_venta_usd REAL DEFAULT 0.0,
    es_perecedero INTEGER NOT NULL DEFAULT 0,
    activo INTEGER NOT NULL DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ----------------------------------------------------------------------------
-- 5. LOTES Y VENCIMIENTOS
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS producto_lotes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    producto_id INTEGER NOT NULL REFERENCES productos(id) ON DELETE CASCADE,
    codigo_lote TEXT NOT NULL,
    fecha_fabricacion DATE,
    fecha_vencimiento DATE NOT NULL,
    cantidad_inicial REAL NOT NULL,
    cantidad_disponible REAL NOT NULL,
    costo_unitario REAL NOT NULL,
    activo INTEGER NOT NULL DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ----------------------------------------------------------------------------
-- 6. CLIENTES Y CUENTAS POR COBRAR (CRÉDITOS / VALES / FIAOS)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS clientes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo_cliente TEXT NOT NULL UNIQUE,
    nombre_completo TEXT NOT NULL,
    carnet_identidad TEXT UNIQUE,
    telefono TEXT,
    direccion TEXT,
    limite_credito REAL NOT NULL DEFAULT 5000.00,
    saldo_deudor_actual REAL NOT NULL DEFAULT 0.00,
    estado_credito TEXT NOT NULL DEFAULT 'ACTIVO' CHECK (estado_credito IN ('ACTIVO', 'SUSPENDIDO', 'BLOQUEADO')),
    observaciones TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ----------------------------------------------------------------------------
-- 7. SESIONES DE CAJA, APERTURAS Y CIERRES (ARQUEOS Z)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS turnos_caja (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    folio_cierre TEXT UNIQUE, -- Z-YYYYMMDD-N
    caja_numero TEXT NOT NULL DEFAULT 'Gaveta 01',
    cajero_id INTEGER NOT NULL REFERENCES usuarios(id),
    supervisor_id INTEGER REFERENCES usuarios(id),
    fecha_apertura DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    fondo_inicial_cup REAL NOT NULL DEFAULT 0.0,
    fondo_inicial_usd REAL NOT NULL DEFAULT 0.0,
    fondo_inicial_mlc REAL NOT NULL DEFAULT 0.0,
    
    fecha_cierre DATETIME,
    estado TEXT NOT NULL DEFAULT 'ABIERTA' CHECK (estado IN ('ABIERTA', 'CERRADA_CONFORME', 'CERRADA_DESCUADRE')),
    
    -- Totales Teóricos por Sistema
    total_ventas_efectivo_cup REAL DEFAULT 0.0,
    total_ventas_transferencia_cup REAL DEFAULT 0.0,
    total_ventas_usd REAL DEFAULT 0.0,
    total_ventas_mlc REAL DEFAULT 0.0,
    total_sangrias_cup REAL DEFAULT 0.0,
    total_abonos_credito_cup REAL DEFAULT 0.0,
    total_egresos_caja_chica_cup REAL DEFAULT 0.0,
    
    -- Arqueo Físico Declarado en Cierre
    efectivo_declarado_cup REAL DEFAULT 0.0,
    efectivo_declarado_usd REAL DEFAULT 0.0,
    efectivo_declarado_mlc REAL DEFAULT 0.0,
    diferencia_cup REAL DEFAULT 0.0, -- (Declarado - Teórico)
    
    justificacion_descuadre TEXT,
    firma_cajero_token TEXT,
    hash_inmutable_sha256 TEXT
);

-- ----------------------------------------------------------------------------
-- 8. RETIROS DE EFECTIVO Y SANGRÍAS A CAJA FUERTE / BÓVEDA
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sangrias_caja (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    folio TEXT NOT NULL UNIQUE, -- SANG-YYYY-XXXX
    turno_id INTEGER NOT NULL REFERENCES turnos_caja(id),
    cajero_id INTEGER NOT NULL REFERENCES usuarios(id),
    autorizado_por INTEGER NOT NULL REFERENCES usuarios(id),
    custodio_boveda_nombre TEXT NOT NULL,
    monto_retirado_cup REAL NOT NULL,
    motivo TEXT NOT NULL DEFAULT 'Exceso de gaveta / Aseguramiento en caja fuerte',
    bolsa_seguridad_numero TEXT,
    hash_sha256 TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ----------------------------------------------------------------------------
-- 9. VENTAS Y COMPROBANTES DE TPV
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ventas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    folio_ticket TEXT NOT NULL UNIQUE, -- TKV-YYYY-XXXXXX
    turno_id INTEGER NOT NULL REFERENCES turnos_caja(id),
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    cliente_id INTEGER REFERENCES clientes(id), -- Null si es consumidor final
    tipo_comprobante TEXT NOT NULL DEFAULT 'TICKET_VENTA' CHECK (tipo_comprobante IN ('TICKET_VENTA', 'VALE_CREDITO', 'DEVOLUCION')),
    metodo_pago TEXT NOT NULL CHECK (metodo_pago IN ('EFECTIVO', 'TRANSFERENCIA', 'MIXTO', 'CREDITO_FICA')),
    
    subtotal_cup REAL NOT NULL,
    descuento_cup REAL NOT NULL DEFAULT 0.0,
    total_neto_cup REAL NOT NULL,
    
    pago_recibido_cup REAL DEFAULT 0.0,
    pago_recibido_usd REAL DEFAULT 0.0,
    pago_recibido_mlc REAL DEFAULT 0.0,
    vuelto_entregado_cup REAL DEFAULT 0.0,
    
    referencia_transferencia TEXT, -- Ref EnZona / Transfermóvil
    estado TEXT NOT NULL DEFAULT 'COMPLETADA' CHECK (estado IN ('COMPLETADA', 'ANULADA')),
    anulada_por INTEGER REFERENCES usuarios(id),
    motivo_anulacion TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS venta_detalles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    venta_id INTEGER NOT NULL REFERENCES ventas(id) ON DELETE CASCADE,
    producto_id INTEGER NOT NULL REFERENCES productos(id),
    lote_id INTEGER REFERENCES producto_lotes(id),
    proveedor_id INTEGER REFERENCES proveedores(id), -- Para devengo de pago a proveedor
    cantidad REAL NOT NULL,
    costo_unitario_historico REAL NOT NULL,
    precio_unitario_cobrado REAL NOT NULL,
    subtotal REAL NOT NULL,
    deuda_generada_proveedor REAL NOT NULL DEFAULT 0.0 -- Monto que se adeuda al proveedor por esta venta
);

-- ----------------------------------------------------------------------------
-- 10. PAGOS DE CLIENTES A CRÉDITO (ABONOS DE FIAOS)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS credito_abonos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    folio_recibo TEXT NOT NULL UNIQUE,
    cliente_id INTEGER NOT NULL REFERENCES clientes(id),
    turno_id INTEGER NOT NULL REFERENCES turnos_caja(id),
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    monto_abonado_cup REAL NOT NULL,
    metodo_pago TEXT NOT NULL CHECK (metodo_pago IN ('EFECTIVO', 'TRANSFERENCIA')),
    referencia_bancaria TEXT,
    saldo_anterior REAL NOT NULL,
    saldo_posterior REAL NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ----------------------------------------------------------------------------
-- 11. RECEPCIONES DE MERCANCÍA (FACTURAS DE ENTRADA / COMPRAS)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS recepciones_mercancia (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    folio_acta TEXT NOT NULL UNIQUE, -- ACTA-REC-YYYY-XXX
    orden_compra_ref TEXT,
    proveedor_id INTEGER NOT NULL REFERENCES proveedores(id),
    factura_conduce_numero TEXT NOT NULL,
    transportista_nombre TEXT NOT NULL,
    transportista_ci TEXT,
    transportista_vehiculo_chapa TEXT,
    almacenero_id INTEGER NOT NULL REFERENCES usuarios(id),
    total_bruto_facturado REAL NOT NULL,
    deduccion_mermas REAL NOT NULL DEFAULT 0.0,
    total_neto_aceptado REAL NOT NULL,
    observaciones TEXT,
    firmado_digitalmente INTEGER NOT NULL DEFAULT 1,
    hash_sha256 TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS recepcion_detalles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recepcion_id INTEGER NOT NULL REFERENCES recepciones_mercancia(id) ON DELETE CASCADE,
    producto_id INTEGER NOT NULL REFERENCES productos(id),
    codigo_lote TEXT,
    fecha_vencimiento DATE,
    cantidad_facturada REAL NOT NULL,
    cantidad_recibida_buena REAL NOT NULL,
    cantidad_danada_merma REAL NOT NULL DEFAULT 0.0,
    costo_unitario_factura REAL NOT NULL,
    pmp_resultante REAL NOT NULL,
    subtotal_neto REAL NOT NULL
);

-- ----------------------------------------------------------------------------
-- 12. COMPROBANTES DE PAGO A PROVEEDORES
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS comprobantes_pago_proveedor (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    folio_comprobante TEXT NOT NULL UNIQUE, -- REC-YYYY-XXXX
    proveedor_id INTEGER NOT NULL REFERENCES proveedores(id),
    usuario_emisor_id INTEGER NOT NULL REFERENCES usuarios(id),
    monto_liquidado_cup REAL NOT NULL,
    canal_pago TEXT NOT NULL CHECK (canal_pago IN ('EFECTIVO_GAVETA', 'EFECTIVO_BOVEDA', 'TRANSFERENCIA_BANCARIA')),
    referencia_bancaria TEXT,
    receptor_nombre TEXT NOT NULL,
    receptor_ci TEXT NOT NULL,
    receptor_vehiculo_chapa TEXT,
    receptor_vinculo TEXT,
    documento_fuente_ref TEXT, -- Folio de liquidación semanal o factura
    hash_sha256 TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ----------------------------------------------------------------------------
-- 13. CAJA CHICA Y GASTOS OPERATIVOS MENORES
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS caja_chica_vales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    folio_vale TEXT NOT NULL UNIQUE, -- VAL-CC-YYYY-XXX
    turno_id INTEGER REFERENCES turnos_caja(id),
    autorizado_por INTEGER NOT NULL REFERENCES usuarios(id),
    beneficiario_nombre TEXT NOT NULL,
    beneficiario_ci TEXT NOT NULL,
    rubro TEXT NOT NULL CHECK (rubro IN ('Insumos y Embalaje', 'Servicios Básicos (UNE/ETECSA)', 'Mantenimiento y Reparación', 'Transporte y Flete', 'Alimentación y Estipendio', 'Otros Gastos')),
    monto_desembolsado_cup REAL NOT NULL,
    concepto_justificacion TEXT NOT NULL,
    compromiso_factura_24h INTEGER NOT NULL DEFAULT 1,
    factura_entregada INTEGER NOT NULL DEFAULT 0,
    hash_sha256 TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ----------------------------------------------------------------------------
-- 14. KARDEX Y CONTROL INMUTABLE DE MOVIMIENTOS
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS kardex_movimientos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    producto_id INTEGER NOT NULL REFERENCES productos(id),
    tipo_movimiento TEXT NOT NULL CHECK (tipo_movimiento IN ('ENTRADA_RECEPCION', 'SALIDA_VENTA', 'BAJA_MERMA', 'AJUSTE_ARQUEO', 'DEVOLUCION_CLIENTE')),
    referencia_folio TEXT NOT NULL, -- Folio de Acta, Ticket o Merma
    lote_id INTEGER REFERENCES producto_lotes(id),
    cantidad REAL NOT NULL,
    stock_previo REAL NOT NULL,
    stock_resultante REAL NOT NULL,
    costo_unitario REAL NOT NULL,
    costo_total REAL NOT NULL,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    hash_sha256 TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ----------------------------------------------------------------------------
-- 15. ACTAS DE BAJA Y MERMAS DE INVENTARIO
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS actas_baja_merma (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    folio_acta TEXT NOT NULL UNIQUE, -- BAJA-YYYY-XXX
    producto_id INTEGER NOT NULL REFERENCES productos(id),
    lote_id INTEGER REFERENCES producto_lotes(id),
    cantidad_baja REAL NOT NULL,
    costo_unitario REAL NOT NULL,
    costo_total_perdida REAL NOT NULL,
    motivo_baja TEXT NOT NULL CHECK (motivo_baja IN ('Vencimiento', 'Rotura / Frasco quebrado', 'Contaminación / Plaga', 'Defecto de Fábrica', 'Pérdida en Transporte')),
    autorizado_por INTEGER NOT NULL REFERENCES usuarios(id),
    testigo_nombre TEXT NOT NULL,
    destino_desecho TEXT NOT NULL DEFAULT 'Destrucción controlada e incineración',
    hash_sha256 TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ----------------------------------------------------------------------------
-- 16. CUADRE SEMANAL Y LIQUIDACIÓN DE GANANCIAS ENTRE SOCIOS
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS liquidaciones_semanales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    folio_liquidacion TEXT NOT NULL UNIQUE, -- LIQ-SEM-YYYY-WW
    semana_periodo TEXT NOT NULL, -- ej. "07-13 Sept"
    fecha_cierre DATE NOT NULL,
    
    -- Conciliación Fiel al Cuadre en Hoja de Cálculo
    efectivo_real_caja REAL NOT NULL,
    transferencias_total REAL NOT NULL DEFAULT 0.0,
    a_pagar_efectivo_proveedores REAL NOT NULL,
    a_pagar_transferencias_proveedores REAL NOT NULL DEFAULT 0.0,
    diferencia_semana REAL NOT NULL DEFAULT 0.0,
    ganancia_semana REAL NOT NULL,
    
    resto_operativo REAL NOT NULL, -- (Efectivo Real - Proveedores - Diferencia)
    resto_mas_ganancias REAL NOT NULL,
    total_efectivo_entre_dos REAL NOT NULL, -- Reparto Socio A y Socio B
    total_transferencia_entre_dos REAL NOT NULL DEFAULT 0.0,
    
    liquidado_por INTEGER NOT NULL REFERENCES usuarios(id),
    observaciones TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ----------------------------------------------------------------------------
-- 17. AUDITORÍA CRIPTOGRÁFICA Y REGISTRO DE INTEGRIDAD
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS auditoria_integridad (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    evento TEXT NOT NULL,
    tabla_afectada TEXT NOT NULL,
    registro_id INTEGER,
    hash_anterior TEXT,
    hash_nuevo TEXT NOT NULL,
    usuario_id INTEGER REFERENCES usuarios(id),
    detalles TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ----------------------------------------------------------------------------
-- ÍNDICES DE ALTO RENDIMIENTO PARA CONSULTAS LOCALES OFFLINE
-- ----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_productos_sku ON productos(sku);
CREATE INDEX IF NOT EXISTS idx_productos_codigo_barras ON productos(codigo_barras);
CREATE INDEX IF NOT EXISTS idx_productos_categoria ON productos(categoria_id);
CREATE INDEX IF NOT EXISTS idx_ventas_folio ON ventas(folio_ticket);
CREATE INDEX IF NOT EXISTS idx_ventas_turno ON ventas(turno_id);
CREATE INDEX IF NOT EXISTS idx_ventas_created ON ventas(created_at);
CREATE INDEX IF NOT EXISTS idx_kardex_producto ON kardex_movimientos(producto_id);
CREATE INDEX IF NOT EXISTS idx_kardex_created ON kardex_movimientos(created_at);
CREATE INDEX IF NOT EXISTS idx_comprobantes_proveedor ON comprobantes_pago_proveedor(proveedor_id);
CREATE INDEX IF NOT EXISTS idx_caja_chica_turno ON caja_chica_vales(turno_id);
CREATE INDEX IF NOT EXISTS idx_lotes_vencimiento ON producto_lotes(fecha_vencimiento);