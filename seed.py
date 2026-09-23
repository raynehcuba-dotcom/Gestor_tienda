#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
GESTOR TIENDA - INICIALIZADOR Y SEEDER DE BASE DE DATOS LOCAL SQLITE
=============================================================================
Este script:
1. Crea la base de datos `tienda_data.db` en modo Write-Ahead Logging (WAL).
2. Aplica el esquema `schema.sql`.
3. Carga los datos semilla con los valores idénticos a los prototipos validados:
   - Usuarios predeterminados (Admin Alejandro, Cajera Laura, Almacén Roberto).
   - Proveedores oficiales (GAIBE S.R.L., EMELYH, Habana Sur, El Trigal).
   - Catálogo de productos con lotes, PMP y fechas de vencimiento.
   - Hoja de cálculo de Cuadre Semanal (Semana 07-13 Sept: $127,950 CUP vs $122,241 CUP).
   - Fondo rotatorio de Caja Chica ($25,000 CUP) y sus vales.
   - Actas de recepción, kardex inicial y cuentas por cobrar.
=============================================================================
"""

import os
import sys
import sqlite3
import hashlib
from datetime import datetime, date, timedelta

DB_FILE = "tienda_data.db"
SCHEMA_FILE = "schema.sql"

def calcular_hash(*args):
    """Calcula un hash SHA-256 inmutable a partir de los datos concatenados."""
    texto = "|".join(str(a) for a in args)
    return hashlib.sha256(texto.encode('utf-8')).hexdigest()

def hash_pin(pin: str) -> str:
    """Hash SHA-256 simple para PIN de TPV."""
    return hashlib.sha256(pin.encode('utf-8')).hexdigest()

def inicializar_bd():
    print(f"[*] Creando o conectando a base de datos local: {DB_FILE}...")
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Habilitar pragmas de rendimiento y resiliencia offline
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute("PRAGMA journal_mode = WAL;")
    cursor.execute("PRAGMA synchronous = NORMAL;")
    cursor.execute("PRAGMA page_size = 4096;")

    # Leer schema.sql si existe en el directorio local, o crearlo en memoria
    if os.path.exists(SCHEMA_FILE):
        print(f"[*] Aplicando DDL desde {SCHEMA_FILE}...")
        with open(SCHEMA_FILE, "r", encoding="utf-8") as f:
            ddl_script = f.read()
        cursor.executescript(ddl_script)
    else:
        print("[!] No se encontró schema.sql en el directorio actual. Asegúrese de guardar el archivo DDL junto a este script.")
        return

    # Verificar si ya tiene datos
    cursor.execute("SELECT COUNT(*) FROM usuarios;")
    if cursor.fetchone()[0] > 0:
        print("[!] La base de datos ya contiene registros. Omitiendo proceso de siembra.")
        conn.close()
        return

    print("[*] Sembrando configuración del negocio...")
    cursor.execute("""
        INSERT INTO configuracion_negocio (
            id, nombre_tienda, razon_social, rut_fiscal, direccion, telefono,
            moneda_principal, tasa_cambio_usd_cup, tasa_cambio_mlc_cup,
            fondo_fijo_caja_chica, tope_vale_caja_chica, margen_utilidad_default
        ) VALUES (
            1, 'Gestor Tienda', 'Gestor Tienda S.R.L.', '40019283741',
            'Calle Principal #102 e/ Central y Línea', '+53 52000000',
            'CUP', 320.00, 270.00, 25000.00, 5000.00, 25.00
        );
    """)

    print("[*] Creando usuarios y roles iniciales...")
    # Admin (PIN: 1234), Cajera (PIN: 2024), Almacenero (PIN: 0104), Socio (PIN: 9999)
    cursor.executemany("""
        INSERT INTO usuarios (nombre_completo, username, pin_hash, password_hash, rol, carnet_identidad, telefono)
        VALUES (?, ?, ?, ?, ?, ?, ?);
    """, [
        ('Alejandro Morales', 'admin', hash_pin('1234'), hash_pin('admin2024*'), 'admin', '85031209841', '+53 53456789'),
        ('Laura González', 'cajera1', hash_pin('2024'), hash_pin('caja2024*'), 'cajero', '92051408321', '+53 54123890'),
        ('Carlos Méndez', 'almacen', hash_pin('0104'), hash_pin('almacen2024*'), 'almacenero', '88102319401', '+53 52998811'),
        ('Roberto V.', 'socio_inversor', hash_pin('9999'), hash_pin('socio2024*'), 'auditor', '78010219432', '+53 53112233')
    ])

    print("[*] Insertando proveedores oficiales...")
    cursor.executemany("""
        INSERT INTO proveedores (codigo_ref, nombre_comercial, razon_social, identificacion_fiscal, contacto_nombre, telefono, tipo_proveedor, saldo_pendiente_efectivo)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?);
    """, [
        ('PROV-001', 'Comercializadora GAIBE S.R.L.', 'GAIBE Soluciones S.R.L.', '40019283741', 'Juan Carlos Pérez Ramos', '+53 52881122', 'Consignación / Venta Devengada', 122241.00),
        ('PROV-002', 'Distribuidora EMELYH', 'EMELYH Alimentos S.R.L.', '40018899211', 'Carlos Viamontes', '+53 53990011', 'Consignación / Venta Devengada', 68400.00),
        ('PROV-003', 'Importadora Habana Sur', 'Habana Sur Trading S.A.', '40017722104', 'Margarita Leyva', '+53 54001122', 'Compra Firme', 15800.00),
        ('PROV-004', 'Proveedor Agropecuario El Trigal', 'Finca El Trigal C.C.S.', '40016633099', 'Orestes Morales', '+53 52114477', 'Compra Firme', 8200.00)
    ])

    print("[*] Insertando categorías de mercancía...")
    cursor.executemany("""
        INSERT INTO categorias (nombre, descripcion) VALUES (?, ?);
    """, [
        ('Bebidas y Licores', 'Refrescos, cervezas, maltas, jugos y aguas'),
        ('Alimentos Secos y Pastas', 'Galletas, harinas, pastas y confitería'),
        ('Aceites y Grasas', 'Aceites vegetales de soya, girasol y mantecas'),
        ('Cárnicos y Embutidos', 'Salchichas, picadillos, jamones y conservas')
    ])

    print("[*] Registrando catálogo de productos y lotes...")
    productos_data = [
        ('REF-CM-15', '78910001', 'Refresco Ciego Montero Cola 1.5L', 1, 1, 'PAQUETE', 120, 20, 410.00, 415.50, 520.00, 'L-2310-A', '2024-09-14'),
        ('CERV-CRIS-355', '78910002', 'Cerveza Cristal Lata 355ml', 1, 1, 'CAJA', 95, 15, 2050.00, 2075.00, 2600.00, 'B-8842', '2024-03-20'),
        ('ACE-VEG-1L', '78910003', 'Aceite Vegetal Refinado 1L', 3, 2, 'CAJA', 60, 10, 1350.00, 1350.00, 1700.00, 'OCT-44', '2024-11-30'),
        ('GAL-SOD-400', '78910004', 'Galletas de Soda Familiares 400g', 2, 2, 'BULTO', 40, 10, 95.00, 98.50, 130.00, 'L-9011', '2024-01-05')
    ]

    for sku, barcode, desc, cat_id, prov_id, unidad, stock, stock_min, c_ult, c_pmp, precio, lote_cod, venc in productos_data:
        cursor.execute("""
            INSERT INTO productos (sku, codigo_barras, descripcion, categoria_id, proveedor_id, unidad_medida, stock_actual, stock_minimo, costo_ultimo, costo_pmp, precio_venta_cup)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, (sku, barcode, desc, cat_id, prov_id, unidad, stock, stock_min, c_ult, c_pmp, precio))
        p_id = cursor.lastrowid
        
        cursor.execute("""
            INSERT INTO producto_lotes (producto_id, codigo_lote, fecha_vencimiento, cantidad_inicial, cantidad_disponible, costo_unitario)
            VALUES (?, ?, ?, ?, ?, ?);
        """, (p_id, lote_cod, venc, stock, stock, c_pmp))

    print("[*] Registrando clientes y créditos (Fiaos)...")
    cursor.executemany("""
        INSERT INTO clientes (codigo_cliente, nombre_completo, carnet_identidad, telefono, limite_credito, saldo_deudor_actual)
        VALUES (?, ?, ?, ?, ?, ?);
    """, [
        ('CLI-001', 'Elena Martínez Ramos', '74081209142', '+53 53882201', 8000.00, 2350.00),
        ('CLI-002', 'Marcos Santana Morales', '85092014389', '+53 52994411', 10000.00, 4800.00),
        ('CLI-003', 'Fabián González', '91031408123', '+53 54009988', 5000.00, 0.00)
    ])

    print("[*] Creando turno de caja activo (Gaveta 01) con fondo inicial...")
    cursor.execute("""
        INSERT INTO turnos_caja (
            caja_numero, cajero_id, fondo_inicial_cup, estado, total_ventas_efectivo_cup, total_ventas_transferencia_cup
        ) VALUES ('Gaveta 01', 2, 5000.00, 'ABIERTA', 127950.00, 0.00);
    """)
    turno_id = cursor.lastrowid

    print("[*] Sembrando vales de Caja Chica (Fondo de $25,000 CUP)...")
    vales = [
        ('VAL-CC-2023-042', 'Raúl Méndez', '88102319401', 'Insumos y Embalaje', 7250.00, 'Compra de 10 paquetes de bolsas nylon camiseta 500u'),
        ('VAL-CC-2023-041', 'Laura González', '92051408321', 'Servicios Básicos (UNE/ETECSA)', 3400.00, 'Pago de factura eléctrica UNE neveras lácteos Comprobante #948210-C'),
        ('VAL-CC-2023-040', 'Laura González', '92051408321', 'Insumos y Embalaje', 1600.00, 'Adquisición de 10 rollos de papel térmico de 80mm TPV'),
        ('VAL-CC-2023-039', 'Mario Rivero', '74011218902', 'Transporte y Flete', 1680.00, 'Flete bicitaxi: traslado 4 cajas aceite vegetal desde almacén anexo'),
        ('VAL-CC-2023-038', 'Ernesto Cabrera', '81090409812', 'Mantenimiento y Reparación', 1250.00, 'Compra de 4 bombillos LED 50W y cinta aislante para mostrador'),
        ('VAL-CC-2023-037', 'Laura González', '92051408321', 'Alimentación y Estipendio', 1400.00, 'Estipendio almuerzo jornada corrida fin de semana (cajeros)')
    ]
    for folio, benef, ci, rubro, monto, conc in vales:
        h = calcular_hash(folio, benef, monto, conc)
        cursor.execute("""
            INSERT INTO caja_chica_vales (
                folio_vale, turno_id, autorizado_por, beneficiario_nombre, beneficiario_ci, rubro, monto_desembolsado_cup, concepto_justificacion, hash_sha256
            ) VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?);
        """, (folio, turno_id, benef, ci, rubro, monto, conc, h))

    print("[*] Registrando Cuadre Semanal (Semana 07-13 Sept) exacto de la plantilla...")
    # Datos conciliados de la hoja de cálculo societaria:
    # EFECTIVO REAL: $127,950.00
    # TRANSFERENCIAS TOTAL: $0.00
    # DIFERENCIA SEMANA: $0.00
    # GANANCIA SEMANA: $1,606.00
    # A PAGAR EFECTIVO PROVEEDORES: $122,241.00
    # RESTO: $5,709.00
    # RESTO MAS GANANCIAS: $7,315.00
    # TOTAL EFECTIVO ENTRE DOS: $3,657.00
    cursor.execute("""
        INSERT INTO liquidaciones_semanales (
            folio_liquidacion, semana_periodo, fecha_cierre, efectivo_real_caja, transferencias_total,
            a_pagar_efectivo_proveedores, a_pagar_transferencias_proveedores, diferencia_semana, ganancia_semana,
            resto_operativo, resto_mas_ganancias, total_efectivo_entre_dos, liquidado_por, observaciones
        ) VALUES (
            'LIQ-SEM-2023-37', 'SEMANA 07-13 Sept', '2023-09-13', 127950.00, 0.00,
            122241.00, 0.00, 0.00, 1606.00,
            5709.00, 7315.00, 3657.00, 1, 'Cuadre verificado conforme con libro de ventas y obligaciones GAIBE.'
        );
    """)

    conn.commit()
    conn.close()
    print("[+] ¡Base de datos SQLite 'tienda_data.db' inicializada y sembrada con éxito!")

if __name__ == "__main__":
    inicializar_bd()