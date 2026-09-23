#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
GESTOR TIENDA (MIPYME) - SERVIDOR DE APLICACIÓN LOCAL Y API SQLITE (app.py)
=============================================================================
Servidor local en Python estándar (sin requerir dependencias complejas)
que ofrece:
1. Servidor HTTP local en el puerto 8000.
2. Despacho de todas las vistas HTML de la tienda (Login, TPV, Inventario, etc.).
3. Endpoints API REST JSON conectados a `tienda_data.db` (SQLite 3 en modo WAL):
   - /api/auth/login (PIN de 4 dígitos o credenciales de admin)
   - /api/productos (Catálogo de productos, stock, precios, alertas)
   - /api/ventas (Registro de tickets, descuento de stock y pasivo a proveedor)
   - /api/turnos/cierre (Arqueo Z, diferencias y hash SHA-256)
   - /api/sangrias (Retiro de gaveta a caja fuerte)
   - /api/caja-chica (Vales de egreso y control de fondo $25,000 CUP)
   - /api/proveedores (Saldos devengados por consignación)
   - /api/liquidaciones (Cuadre semanal 50/50 y hojas de liquidación)
   - /api/respaldo (Ejecución de checkpoint WAL y copia USB)
=============================================================================
"""

import os
import sys
import json
import sqlite3
import hashlib
import mimetypes
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

DB_FILE = "tienda_data.db"
PORT = 8000

# ---------------------------------------------------------------------------
# UTILIDADES DE BASE DE DATOS Y CRIPTOGRAFÍA
# ---------------------------------------------------------------------------
def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    return conn

def hash_sha256(texto: str) -> str:
    return hashlib.sha256(texto.encode('utf-8')).hexdigest()

# ---------------------------------------------------------------------------
# CONTROLADOR PRINCIPAL DEL SERVIDOR HTTP Y API
# ---------------------------------------------------------------------------
class GestorTiendaHandler(BaseHTTPRequestHandler):

    def _set_headers(self, status=200, content_type="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_OPTIONS(self):
        self._set_headers(200)

    # -----------------------------------------------------------------------
    # MANEJO DE RUTAS GET (ARCHIVOS ESTÁTICOS HTML + ENDPOINTS API)
    # -----------------------------------------------------------------------
    def do_GET(self):
        parsed_url = urlparse(self.path)
        path = parsed_url.path

        # 1. API: Listado de Productos / Stock para TPV
        if path == "/api/productos":
            self.handle_get_productos(parsed_url.query)
            return

        # 2. API: Proveedores y saldos devengados
        if path == "/api/proveedores":
            self.handle_get_proveedores()
            return

        # 3. API: Caja Chica y Vales de egreso
        if path == "/api/caja-chica":
            self.handle_get_caja_chica()
            return

        # 4. API: Clientes y Cuentas por Cobrar (Fiados)
        if path == "/api/clientes":
            self.handle_get_clientes()
            return

        # 5. API: Cuadre Semanal y Liquidaciones de Socios
        if path == "/api/liquidaciones":
            self.handle_get_liquidaciones()
            return

        # 6. API: Turno activo de caja
        if path == "/api/turnos/activo":
            self.handle_get_turno_activo()
            return

        # 7. API: Métricas generales de Dashboard
        if path == "/api/dashboard/kpis":
            self.handle_get_dashboard_kpis()
            return

        # 8. Servidor de Archivos HTML y Estáticos
        self.serve_static_file(path)

    # -----------------------------------------------------------------------
    # MANEJO DE RUTAS POST (TRANSACCIONES Y ESCRITURA CON SQLite WAL)
    # -----------------------------------------------------------------------
    def do_POST(self):
        parsed_url = urlparse(self.path)
        path = parsed_url.path

        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode('utf-8') if content_length > 0 else "{}"
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            data = {}

        # 1. Autenticación con PIN o usuario
        if path == "/api/auth/login":
            self.handle_post_login(data)
            return

        # 2. Registrar nueva Venta (TPV)
        if path == "/api/ventas":
            self.handle_post_venta(data)
            return

        # 3. Registrar Cierre de Caja (Arqueo Z)
        if path == "/api/turnos/cierre":
            self.handle_post_cierre_caja(data)
            return

        # 4. Registrar Sangría a Bóveda / Caja Fuerte
        if path == "/api/sangrias":
            self.handle_post_sangria(data)
            return

        # 5. Registrar Vale de Caja Chica
        if path == "/api/caja-chica/vales":
            self.handle_post_vale_caja_chica(data)
            return

        # 6. Registrar Abono de Fiado (Cliente)
        if path == "/api/clientes/abono":
            self.handle_post_abono_cliente(data)
            return

        # 7. Registrar Cuadre Semanal de Socios
        if path == "/api/liquidaciones/guardar":
            self.handle_post_liquidacion_semanal(data)
            return

        # 8. Ejecutar Respaldo Inmediato (Checkpoint WAL + Backup)
        if path == "/api/respaldo/ejecutar":
            self.handle_post_respaldo_sqlite()
            return

        self._set_headers(404)
        self.wfile.write(json.dumps({"error": "Endpoint no encontrado"}).encode())

    # -----------------------------------------------------------------------
    # CONTROLADORES DE LECTURA (GET HANDLERS)
    # -----------------------------------------------------------------------
    def handle_get_productos(self, query_string):
        params = parse_qs(query_string)
        buscar = params.get('q', [''])[0]
        conn = get_db()
        cursor = conn.cursor()
        if buscar:
            cursor.execute("""
                SELECT p.*, c.nombre as categoria_nombre, pr.nombre_comercial as proveedor_nombre
                FROM productos p
                JOIN categorias c ON p.categoria_id = c.id
                LEFT JOIN proveedores pr ON p.proveedor_id = pr.id
                WHERE p.descripcion LIKE ? OR p.sku LIKE ? OR p.codigo_barras LIKE ?
                ORDER BY p.descripcion ASC
            """, (f"%{buscar}%", f"%{buscar}%", f"%{buscar}%"))
        else:
            cursor.execute("""
                SELECT p.*, c.nombre as categoria_nombre, pr.nombre_comercial as proveedor_nombre
                FROM productos p
                JOIN categorias c ON p.categoria_id = c.id
                LEFT JOIN proveedores pr ON p.proveedor_id = pr.id
                WHERE p.activo = 1
                ORDER BY p.descripcion ASC
            """)
        productos = [dict(row) for row in cursor.fetchall()]
        conn.close()
        self._set_headers(200)
        self.wfile.write(json.dumps({"productos": productos}).encode())

    def handle_get_proveedores(self):
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM proveedores WHERE activo = 1 ORDER BY nombre_comercial ASC")
        proveedores = [dict(row) for row in cursor.fetchall()]
        conn.close()
        self._set_headers(200)
        self.wfile.write(json.dumps({"proveedores": proveedores}).encode())

    def handle_get_caja_chica(self):
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM configuracion_negocio WHERE id = 1")
        config = dict(cursor.fetchone() or {})
        fondo_fijo = config.get('fondo_fijo_caja_chica', 25000.0)

        cursor.execute("SELECT * FROM caja_chica_vales ORDER BY id DESC LIMIT 50")
        vales = [dict(row) for row in cursor.fetchall()]
        total_desembolsado = sum(v['monto_desembolsado_cup'] for v in vales)
        saldo_disponible = fondo_fijo - total_desembolsado

        conn.close()
        self._set_headers(200)
        self.wfile.write(json.dumps({
            "fondo_fijo": fondo_fijo,
            "total_desembolsado": total_desembolsado,
            "saldo_disponible": max(0.0, saldo_disponible),
            "vales": vales
        }).encode())

    def handle_get_clientes(self):
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM clientes ORDER BY nombre_completo ASC")
        clientes = [dict(row) for row in cursor.fetchall()]
        conn.close()
        self._set_headers(200)
        self.wfile.write(json.dumps({"clientes": clientes}).encode())

    def handle_get_liquidaciones(self):
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM liquidaciones_semanales ORDER BY id DESC LIMIT 10")
        liquidaciones = [dict(row) for row in cursor.fetchall()]
        conn.close()
        self._set_headers(200)
        self.wfile.write(json.dumps({"liquidaciones": liquidaciones}).encode())

    def handle_get_turno_activo(self):
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT t.*, u.nombre_completo as cajero_nombre, u.rol
            FROM turnos_caja t
            JOIN usuarios u ON t.cajero_id = u.id
            WHERE t.estado = 'ABIERTA'
            ORDER BY t.id DESC LIMIT 1
        """)
        turno = cursor.fetchone()
        conn.close()
        self._set_headers(200)
        if turno:
            self.wfile.write(json.dumps({"turno": dict(turno)}).encode())
        else:
            self.wfile.write(json.dumps({"turno": None, "mensaje": "No hay gaveta abierta actualmente"}).encode())

    def handle_get_dashboard_kpis(self):
        conn = get_db()
        cursor = conn.cursor()
        # Ventas de hoy
        cursor.execute("""
            SELECT COUNT(*) as cantidad, COALESCE(SUM(total_neto_cup), 0.0) as total_ventas
            FROM ventas WHERE DATE(created_at) = DATE('now', 'localtime') AND estado = 'COMPLETADA'
        """)
        ventas_hoy = dict(cursor.fetchone())

        # Total proveedores pendientes
        cursor.execute("SELECT COALESCE(SUM(saldo_pendiente_efectivo), 0.0) as deuda_prov FROM proveedores WHERE activo = 1")
        prov_deuda = cursor.fetchone()['deuda_prov']

        # Total productos con alerta de stock
        cursor.execute("SELECT COUNT(*) as bajo_stock FROM productos WHERE stock_actual <= stock_minimo AND activo = 1")
        bajo_stock = cursor.fetchone()['bajo_stock']

        conn.close()
        self._set_headers(200)
        self.wfile.write(json.dumps({
            "ventas_hoy_monto": ventas_hoy['total_ventas'],
            "ventas_hoy_cantidad": ventas_hoy['cantidad'],
            "deuda_proveedores_efectivo": prov_deuda,
            "productos_alerta_stock": bajo_stock
        }).encode())

    # -----------------------------------------------------------------------
    # CONTROLADORES DE ESCRITURA / TRANSACCIONES (POST HANDLERS)
    # -----------------------------------------------------------------------
    def handle_post_login(self, data):
        pin = str(data.get("pin", "")).strip()
        username = str(data.get("username", "")).strip()
        password = str(data.get("password", "")).strip()

        conn = get_db()
        cursor = conn.cursor()

        if pin:
            p_hash = hash_sha256(pin)
            cursor.execute("SELECT id, nombre_completo, username, rol FROM usuarios WHERE pin_hash = ? AND activo = 1", (p_hash,))
            user = cursor.fetchone()
        elif username and password:
            pwd_hash = hash_sha256(password)
            cursor.execute("SELECT id, nombre_completo, username, rol FROM usuarios WHERE username = ? AND password_hash = ? AND activo = 1", (username, pwd_hash))
            user = cursor.fetchone()
        else:
            user = None

        conn.close()
        if user:
            self._set_headers(200)
            self.wfile.write(json.dumps({"success": True, "usuario": dict(user)}).encode())
        else:
            self._set_headers(401)
            self.wfile.write(json.dumps({"success": False, "error": "PIN o credenciales no válidas"}).encode())

    def handle_post_venta(self, data):
        """
        Transacción de Venta (TPV):
        1. Inserta el ticket en `ventas`.
        2. Inserta cada ítem en `venta_detalles`.
        3. Descuenta existencias en `productos` y `producto_lotes`.
        4. Si el producto pertenece a un proveedor en consignación, devenga el saldo a `proveedores`.
        5. Actualiza los totales acumulados del turno activo en `turnos_caja`.
        """
        conn = get_db()
        try:
            cursor = conn.cursor()
            folio_ticket = f"TKV-{datetime.now().strftime('%Y%m%d')}-{int(datetime.now().timestamp()) % 100000:05d}"
            turno_id = data.get("turno_id", 1)
            usuario_id = data.get("usuario_id", 1)
            cliente_id = data.get("cliente_id")
            metodo_pago = data.get("metodo_pago", "EFECTIVO")
            subtotal = float(data.get("subtotal", 0.0))
            descuento = float(data.get("descuento", 0.0))
            total_neto = float(data.get("total_neto", subtotal - descuento))
            pago_recibido = float(data.get("pago_recibido", total_neto))
            vuelto = max(0.0, pago_recibido - total_neto)
            lineas = data.get("items", [])

            cursor.execute("""
                INSERT INTO ventas (
                    folio_ticket, turno_id, usuario_id, cliente_id, metodo_pago,
                    subtotal_cup, descuento_cup, total_neto_cup, pago_recibido_cup, vuelto_entregado_cup
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (folio_ticket, turno_id, usuario_id, cliente_id, metodo_pago, subtotal, descuento, total_neto, pago_recibido, vuelto))
            venta_id = cursor.lastrowid

            for item in lineas:
                prod_id = item['producto_id']
                cant = float(item['cantidad'])
                precio_unit = float(item['precio_unitario'])
                costo_unit = float(item.get('costo_unitario', 0.0))
                sub_linea = cant * precio_unit

                # Obtener proveedor asignado
                cursor.execute("SELECT proveedor_id, stock_actual FROM productos WHERE id = ?", (prod_id,))
                p_row = cursor.fetchone()
                prov_id = p_row['proveedor_id'] if p_row else None
                deuda_prov = (cant * costo_unit) if prov_id else 0.0

                # Insertar detalle de venta
                cursor.execute("""
                    INSERT INTO venta_detalles (
                        venta_id, producto_id, proveedor_id, cantidad, costo_unitario_historico,
                        precio_unitario_cobrado, subtotal, deuda_generada_proveedor
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """, (venta_id, prod_id, prov_id, cant, costo_unit, precio_unit, sub_linea, deuda_prov))

                # Descontar stock
                cursor.execute("UPDATE productos SET stock_actual = stock_actual - ? WHERE id = ?", (cant, prod_id))

                # Asentar en Kardex
                k_hash = hash_sha256(f"SALIDA_VENTA|{folio_ticket}|{prod_id}|{cant}")
                cursor.execute("""
                    INSERT INTO kardex_movimientos (
                        producto_id, tipo_movimiento, referencia_folio, cantidad,
                        stock_previo, stock_resultante, costo_unitario, costo_total, usuario_id, hash_sha256
                    ) VALUES (?, 'SALIDA_VENTA', ?, ?, ?, ?, ?, ?, ?, ?);
                """, (prod_id, folio_ticket, cant, p_row['stock_actual'], p_row['stock_actual'] - cant, costo_unit, deuda_prov, usuario_id, k_hash))

                # Si es mercancía en consignación, incrementar saldo pendiente al proveedor
                if prov_id and deuda_prov > 0:
                    cursor.execute("""
                        UPDATE proveedores
                        SET saldo_pendiente_efectivo = saldo_pendiente_efectivo + ?
                        WHERE id = ?;
                    """, (deuda_prov, prov_id))

            # Actualizar totales del turno de caja
            if metodo_pago == "EFECTIVO":
                cursor.execute("UPDATE turnos_caja SET total_ventas_efectivo_cup = total_ventas_efectivo_cup + ? WHERE id = ?", (total_neto, turno_id))
            else:
                cursor.execute("UPDATE turnos_caja SET total_ventas_transferencia_cup = total_ventas_transferencia_cup + ? WHERE id = ?", (total_neto, turno_id))

            conn.commit()
            conn.close()

            self._set_headers(201)
            self.wfile.write(json.dumps({
                "success": True,
                "folio_ticket": folio_ticket,
                "total_neto": total_neto,
                "vuelto": vuelto
            }).encode())
        except Exception as e:
            conn.rollback()
            conn.close()
            self._set_headers(500)
            self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode())

    def handle_post_cierre_caja(self, data):
        """Arqueo Z ciego y registro con hash SHA-256."""
        conn = get_db()
        try:
            cursor = conn.cursor()
            turno_id = data.get("turno_id")
            efectivo_declarado = float(data.get("efectivo_declarado", 0.0))
            justificacion = data.get("justificacion_descuadre", "")

            # Obtener datos teóricos del turno
            cursor.execute("SELECT * FROM turnos_caja WHERE id = ?", (turno_id,))
            turno = cursor.fetchone()
            if not turno:
                raise ValueError("Turno no encontrado")

            teorico = (turno['fondo_inicial_cup'] + turno['total_ventas_efectivo_cup'] + turno['total_abonos_credito_cup']
                       - turno['total_sangrias_cup'] - turno['total_egresos_caja_chica_cup'])
            diferencia = efectivo_declarado - teorico
            estado = "CERRADA_CONFORME" if abs(diferencia) < 0.01 else "CERRADA_DESCUADRE"
            folio_z = f"Z-{datetime.now().strftime('%Y%m%d')}-{turno_id:04d}"
            h_sha = hash_sha256(f"{folio_z}|{efectivo_declarado}|{teorico}|{diferencia}")

            cursor.execute("""
                UPDATE turnos_caja
                SET folio_cierre = ?, fecha_cierre = CURRENT_TIMESTAMP, estado = ?,
                    efectivo_declarado_cup = ?, diferencia_cup = ?, justificacion_descuadre = ?,
                    hash_inmutable_sha256 = ?
                WHERE id = ?;
            """, (folio_z, estado, efectivo_declarado, diferencia, justificacion, h_sha, turno_id))

            conn.commit()
            conn.close()
            self._set_headers(200)
            self.wfile.write(json.dumps({
                "success": True,
                "folio_cierre": folio_z,
                "estado": estado,
                "teorico": teorico,
                "declarado": efectivo_declarado,
                "diferencia": diferencia,
                "hash_sha256": h_sha
            }).encode())
        except Exception as e:
            conn.rollback()
            conn.close()
            self._set_headers(500)
            self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode())

    def handle_post_sangria(self, data):
        conn = get_db()
        try:
            cursor = conn.cursor()
            turno_id = data.get("turno_id", 1)
            cajero_id = data.get("cajero_id", 1)
            autorizado_por = data.get("autorizado_por", 1)
            custodio = data.get("custodio_boveda_nombre", "Custodio Bóveda")
            monto = float(data.get("monto_retirado_cup", 50000.0))
            bolsa = data.get("bolsa_seguridad_numero", "B-99812")
            folio = f"SANG-{datetime.now().strftime('%Y')}-{int(datetime.now().timestamp()) % 10000:04d}"
            h = hash_sha256(f"{folio}|{monto}|{custodio}|{bolsa}")

            cursor.execute("""
                INSERT INTO sangrias_caja (
                    folio, turno_id, cajero_id, autorizado_por, custodio_boveda_nombre,
                    monto_retirado_cup, bolsa_seguridad_numero, hash_sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """, (folio, turno_id, cajero_id, autorizado_por, custodio, monto, bolsa, h))

            cursor.execute("UPDATE turnos_caja SET total_sangrias_cup = total_sangrias_cup + ? WHERE id = ?", (monto, turno_id))

            conn.commit()
            conn.close()
            self._set_headers(201)
            self.wfile.write(json.dumps({"success": True, "folio": folio, "hash_sha256": h}).encode())
        except Exception as e:
            conn.rollback()
            conn.close()
            self._set_headers(500)
            self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode())

    def handle_post_vale_caja_chica(self, data):
        conn = get_db()
        try:
            cursor = conn.cursor()
            benef = data.get("beneficiario_nombre", "")
            ci = data.get("beneficiario_ci", "")
            rubro = data.get("rubro", "Insumos y Embalaje")
            monto = float(data.get("monto_desembolsado_cup", 0.0))
            concepto = data.get("concepto_justificacion", "")
            folio = f"VAL-CC-{datetime.now().strftime('%Y')}-{int(datetime.now().timestamp()) % 1000:03d}"
            h = hash_sha256(f"{folio}|{benef}|{monto}|{concepto}")

            cursor.execute("""
                INSERT INTO caja_chica_vales (
                    folio_vale, autorizado_por, beneficiario_nombre, beneficiario_ci,
                    rubro, monto_desembolsado_cup, concepto_justificacion, hash_sha256
                ) VALUES (?, 1, ?, ?, ?, ?, ?, ?);
            """, (folio, benef, ci, rubro, monto, concepto, h))

            conn.commit()
            conn.close()
            self._set_headers(201)
            self.wfile.write(json.dumps({"success": True, "folio_vale": folio, "hash_sha256": h}).encode())
        except Exception as e:
            conn.rollback()
            conn.close()
            self._set_headers(500)
            self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode())

    def handle_post_abono_cliente(self, data):
        conn = get_db()
        try:
            cursor = conn.cursor()
            cli_id = data.get("cliente_id")
            monto = float(data.get("monto_abonado_cup", 0.0))
            turno_id = data.get("turno_id", 1)
            usuario_id = data.get("usuario_id", 1)

            cursor.execute("SELECT saldo_deudor_actual FROM clientes WHERE id = ?", (cli_id,))
            c_row = cursor.fetchone()
            saldo_ant = c_row['saldo_deudor_actual']
            saldo_post = max(0.0, saldo_ant - monto)

            folio = f"ABO-{datetime.now().strftime('%Y%m')}-{int(datetime.now().timestamp()) % 10000:04d}"
            cursor.execute("""
                INSERT INTO credito_abonos (
                    folio_recibo, cliente_id, turno_id, usuario_id, monto_abonado_cup,
                    metodo_pago, saldo_anterior, saldo_posterior
                ) VALUES (?, ?, ?, ?, ?, 'EFECTIVO', ?, ?);
            """, (folio, cli_id, turno_id, usuario_id, monto, saldo_ant, saldo_post))

            cursor.execute("UPDATE clientes SET saldo_deudor_actual = ? WHERE id = ?", (saldo_post, cli_id))
            cursor.execute("UPDATE turnos_caja SET total_abonos_credito_cup = total_abonos_credito_cup + ? WHERE id = ?", (monto, turno_id))

            conn.commit()
            conn.close()
            self._set_headers(201)
            self.wfile.write(json.dumps({"success": True, "folio_recibo": folio, "saldo_posterior": saldo_post}).encode())
        except Exception as e:
            conn.rollback()
            conn.close()
            self._set_headers(500)
            self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode())

    def handle_post_liquidacion_semanal(self, data):
        conn = get_db()
        try:
            cursor = conn.cursor()
            semana = data.get("semana_periodo", "SEMANA")
            efectivo_real = float(data.get("efectivo_real_caja", 0.0))
            a_pagar_prov = float(data.get("a_pagar_efectivo_proveedores", 0.0))
            diferencia = float(data.get("diferencia_semana", 0.0))
            ganancia = float(data.get("ganancia_semana", 0.0))
            resto = efectivo_real - a_pagar_prov - diferencia
            resto_mas_ganancias = resto + ganancia
            por_socio = resto_mas_ganancias / 2.0

            folio = f"LIQ-SEM-{datetime.now().strftime('%Y')}-{datetime.now().strftime('%W')}"
            cursor.execute("""
                INSERT INTO liquidaciones_semanales (
                    folio_liquidacion, semana_periodo, fecha_cierre, efectivo_real_caja,
                    a_pagar_efectivo_proveedores, diferencia_semana, ganancia_semana,
                    resto_operativo, resto_mas_ganancias, total_efectivo_entre_dos, liquidado_por
                ) VALUES (?, ?, CURRENT_DATE, ?, ?, ?, ?, ?, ?, ?, 1);
            """, (folio, semana, efectivo_real, a_pagar_prov, diferencia, ganancia, resto, resto_mas_ganancias, por_socio))

            conn.commit()
            conn.close()
            self._set_headers(201)
            self.wfile.write(json.dumps({
                "success": True,
                "folio_liquidacion": folio,
                "resto_operativo": resto,
                "total_entre_dos": por_socio
            }).encode())
        except Exception as e:
            conn.rollback()
            conn.close()
            self._set_headers(500)
            self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode())

    def handle_post_respaldo_sqlite(self):
        try:
            conn = get_db()
            conn.execute("PRAGMA wal_checkpoint(PASSIVE);")
            conn.close()

            backup_dir = "backups"
            if not os.path.exists(backup_dir):
                os.makedirs(backup_dir)

            t_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            dest_file = os.path.join(backup_dir, f"respaldo_manual_{t_stamp}.db")

            src = sqlite3.connect(DB_FILE)
            dst = sqlite3.connect(dest_file)
            src.backup(dst)
            dst.close()
            src.close()

            with open(dest_file, "rb") as f:
                h_val = hashlib.sha256(f.read()).hexdigest()

            self._set_headers(200)
            self.wfile.write(json.dumps({
                "success": True,
                "archivo": dest_file,
                "hash_sha256": h_val,
                "mensaje": "Checkpoint WAL consolidado y clonación SQLite completada"
            }).encode())
        except Exception as e:
            self._set_headers(500)
            self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode())

    # -----------------------------------------------------------------------
    # SERVIDOR DE ARCHIVOS ESTÁTICOS / DESPACHO DE VISTAS HTML
    # -----------------------------------------------------------------------
    def serve_static_file(self, path):
        if path == "/" or path == "":
            path = "/index.html"

        # Quitar el slash inicial para ruta local
        clean_path = path.lstrip("/")
        
        # Mapa de alias cómodos para navegar en navegador
        aliases = {
            "pos": "pos.html",
            "tpv": "pos.html",
            "inventario": "inventario.html",
            "cierre": "cierre_caja.html",
            "caja-chica": "caja_chica.html",
            "sangria": "sangria.html",
            "proveedores": "proveedores.html",
            "cuadre": "cuadre_semanal.html",
            "kardex": "kardex.html",
            "clientes": "clientes.html",
            "dashboard": "dashboard.html",
            "mantenimiento": "mantenimiento.html"
        }
        if clean_path in aliases:
            clean_path = aliases[clean_path]

        if not os.path.exists(clean_path):
            self._set_headers(404, "text/html")
            self.wfile.write(b"<h1>404 - Archivo no encontrado en Gestor Tienda</h1><p><a href='/'>Volver al inicio</a></p>")
            return

        mime_type, _ = mimetypes.guess_type(clean_path)
        if mime_type is None:
            mime_type = "application/octet-stream"

        try:
            with open(clean_path, "rb") as f:
                content = f.read()
            self._set_headers(200, mime_type)
            self.wfile.write(content)
        except Exception as e:
            self._set_headers(500, "text/plain")
            self.wfile.write(f"Error al leer el archivo: {e}".encode())

# ---------------------------------------------------------------------------
# INICIO DEL SERVIDOR
# ---------------------------------------------------------------------------
def run_server():
    if not os.path.exists(DB_FILE):
        print(f"[!] No se detectó {DB_FILE}. Ejecute primero 'python seed.py' para inicializar los datos.")

    server_address = ('', PORT)
    httpd = HTTPServer(server_address, GestorTiendaHandler)
    print("=" * 78)
    print(f"  GESTOR TIENDA - SERVIDOR LOCAL CONECTADO A SQLITE ACTIVO")
    print(f"  URL Local: http://localhost:{PORT}")
    print(f"  Base de Datos: {DB_FILE} (Modo WAL)")
    print("=" * 78)
    print("[*] Presione CTRL + C para detener el servidor con seguridad.\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[+] Servidor detenido con éxito por el usuario.")
        httpd.server_close()

if __name__ == "__main__":
    run_server()
