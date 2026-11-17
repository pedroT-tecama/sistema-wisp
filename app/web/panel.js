/*
  Lógica del panel de operación (app/web/index.html).
  Qué hace: llama a las rutas de la API del sistema con fetch y muestra las respuestas en tablas,
  fichas y una gráfica. No contiene reglas de negocio; las validaciones y los cálculos los hace la API.
  Rutas que usa (todas existen en el backend; ver /docs):
    Abonados  -> GET /abonados?buscar=, GET /abonados/{id}, POST /abonados/{id}/pagos, POST /abonados/{id}/suspension
    Nuevo     -> POST /abonados, GET /monitoreo/ruteadores (ruteadores), GET /consultas/planes (planes)
    Órdenes   -> GET /ordenes?estado=, POST /ordenes/despachar
    Monitoreo -> GET /monitoreo/ruteadores, GET /monitoreo/alertas?abiertas=, POST /monitoreo/evaluar
    Enlaces   -> GET /enlaces, GET /enlaces/{id}/lecturas (app/routers/enlaces.py)
    Red       -> GET /consultas/topologia (app/routers/consultas.py)
    Avisos    -> GET /monitoreo/alertas?abiertas=true cada 30 s, en cualquier pestaña
*/

// ------------------------------------------------------------ utilidades
const $ = (s) => document.querySelector(s);
const fmtFecha = (f) => f ? new Date(f).toLocaleDateString('es-PE', { timeZone: 'UTC' }) : '—';
const fmtHora = (f) => f ? new Date(f).toLocaleString('es-PE') : '—';
const esc = (t) => String(t ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

// Llama a la API y devuelve el JSON; si la API responde con error, lanza su mensaje legible.
async function api(ruta, metodo = 'GET', cuerpo = null) {
  const op = { method: metodo, headers: {} };
  if (cuerpo) { op.headers['Content-Type'] = 'application/json'; op.body = JSON.stringify(cuerpo); }
  const r = await fetch(ruta, op);
  const datos = await r.json().catch(() => ({}));
  if (!r.ok) {
    const d = datos.detail;
    // 422: lista de errores de validación (campo y mensaje); 404/409: texto del servicio
    const texto = Array.isArray(d) ? d.map((e) => `${e.loc.slice(-1)[0]}: ${e.msg}`).join(' · ') : (d || `Error ${r.status}`);
    throw new Error(texto);
  }
  return datos;
}

// Mensaje de confirmación o de error en la parte superior.
function avisar(texto, tipo = 'ok') {
  const a = $('#aviso'); a.textContent = texto; a.className = `aviso ${tipo}`;
  clearTimeout(avisar.t); avisar.t = setTimeout(() => a.classList.add('oculto'), 7000);
}

// Etiqueta de color para los estados del abonado, de las órdenes y de los ruteadores.
function etiqueta(estado) {
  const ok = ['ACTIVO', 'PROCESADO', 'CHECK_OK'], mal = ['SUSPENDIDO', 'NODO_CAIDO'];
  const c = ok.includes(estado) ? 'e-ok' : mal.includes(estado) ? 'e-mal' : 'e-amb';
  return `<span class="estado ${c}">${esc(estado)}</span>`;
}

function tabla(sel, cabeceras, filas, alClic) {
  const t = $(sel);
  t.innerHTML = `<tr>${cabeceras.map((c) => `<th>${c}</th>`).join('')}</tr>` +
    (filas.length ? filas.map((f, i) => `<tr data-i="${i}" class="${alClic ? 'clic' : ''}">${f.map((v) => `<td>${v}</td>`).join('')}</tr>`).join('')
      : `<tr><td colspan="${cabeceras.length}" class="tenue">Sin resultados</td></tr>`);
  if (alClic) t.querySelectorAll('tr[data-i]').forEach((tr) => tr.onclick = () => alClic(+tr.dataset.i));
}

// ------------------------------------------------------------ pestañas
let temporizador = null;   // actualización automática de Monitoreo y Enlaces
document.querySelectorAll('#pestanas button').forEach((b) => b.onclick = () => abrirPestana(b.dataset.p));
function abrirPestana(p) {
  document.querySelectorAll('#pestanas button').forEach((b) => b.classList.toggle('activa', b.dataset.p === p));
  document.querySelectorAll('.pestana').forEach((s) => s.classList.toggle('oculto', s.id !== `p-${p}`));
  clearInterval(temporizador);
  if (p === 'nuevo') cargarRuteadoresSelect();
  if (p === 'ordenes') cargarOrdenes();
  if (p === 'monitoreo') { cargarMonitoreo(); temporizador = setInterval(cargarMonitoreo, 30000); }
  if (p === 'enlaces') iniciarEnlaces();
  if (p === 'red') { cargarRed(); temporizador = setInterval(cargarRed, 30000); }
}

// ------------------------------------------------------------ 1. Abonados (HU-02, HU-03)
let resultados = [];
$('#f-buscar').onsubmit = async (e) => {
  e.preventDefault();
  try {
    resultados = await api(`/abonados?buscar=${encodeURIComponent($('#buscar').value.trim())}`);
    tabla('#t-abonados', ['Id', 'Apellidos', 'Nombres', 'DNI', 'Ruteador', 'Estado', 'Vence'],
      resultados.map((a) => [a.id, esc(a.apellidos), esc(a.nombres), esc(a.dni), esc(a.router.nombre_equipo), etiqueta(a.estado), fmtFecha(a.fecha_vencimiento)]),
      (i) => verFicha(resultados[i].id));
    $('#ficha').classList.add('oculto');
  } catch (err) { avisar(err.message, 'error'); }
};

async function verFicha(id) {
  try {
    const a = await api(`/abonados/${id}`);
    const f = $('#ficha');
    f.innerHTML = `<h3>${esc(a.apellidos)}, ${esc(a.nombres)} ${etiqueta(a.estado)}</h3>
      <div class="datos">
        <b>DNI</b><span>${esc(a.dni)}</span><b>Dirección</b><span>${esc(a.direccion)}</span>
        <b>IP / MAC</b><span>${esc(a.ip_cliente)} / ${esc(a.mac_cliente || '—')}</span><b>Ruteador</b><span>${esc(a.router.nombre_equipo)}</span>
        <b>Plan</b><span>${esc(a.tarifa.nombre_plan)} (S/ ${a.tarifa.precio_mensual})</span><b>Velocidad</b><span>${esc(a.tarifa.rate_download)} / ${esc(a.tarifa.rate_upload)}</span>
        <b>Vencimiento</b><span>${fmtFecha(a.fecha_vencimiento)}</span><b>Día de pago</b><span>${a.dia_pago}</span>
        <b>Corte efectivo</b><span>${fmtFecha(a.fecha_corte_efectivo)}</span><b>Días a favor</b><span>${a.saldo_dias_favor}</span>
      </div>
      <div class="acciones">
        <label class="tenue">Monto (S/)<br><input id="pg-monto" type="number" step="0.01" min="0.01" value="${a.tarifa.precio_mensual}"></label>
        <label class="tenue">Medio de pago<br><input id="pg-medio" value="Efectivo" maxlength="30"></label>
        <label class="tenue">Fecha (opcional)<br><input id="pg-fecha" type="date"></label>
        <button id="b-pagar">Registrar pago</button>
        ${a.estado === 'ACTIVO' ? '<button id="b-suspender" class="peligro">Suspender servicio</button>' : ''}
      </div>`;
    f.classList.remove('oculto');
    $('#b-pagar').onclick = () => pagar(a.id);
    if ($('#b-suspender')) $('#b-suspender').onclick = () => suspender(a);
  } catch (err) { avisar(err.message, 'error'); }
}

async function pagar(id) {
  const cuerpo = { monto: $('#pg-monto').value, medio_pago: $('#pg-medio').value.trim() };
  if ($('#pg-fecha').value) cuerpo.fecha_pago = $('#pg-fecha').value;
  try {
    const r = await api(`/abonados/${id}/pagos`, 'POST', cuerpo);
    avisar(`${r.mensaje} Nuevo vencimiento: ${fmtFecha(r.nuevo_vencimiento)}.`);
    verFicha(id);
  } catch (err) { avisar(err.message, 'error'); }
}

async function suspender(a) {
  if (!confirm(`¿Suspender el servicio de ${a.nombres} ${a.apellidos}? Se encolará la orden de corte.`)) return;
  try {
    const r = await api(`/abonados/${a.id}/suspension`, 'POST');
    avisar(r.mensaje);
    verFicha(a.id);
  } catch (err) { avisar(err.message, 'error'); }
}

// ------------------------------------------------------------ 2. Nuevo abonado (HU-01)
async function cargarRuteadoresSelect() {
  try {
    const [rs, ps] = await Promise.all([api('/monitoreo/ruteadores'), api('/consultas/planes')]);
    $('#sel-router').innerHTML = rs.map((r) => `<option value="${r.id}">${esc(r.nombre_equipo)} (${esc(r.ip_router)})</option>`).join('');
    $('#sel-plan').innerHTML = ps.map((p) => `<option value="${p.id}">${esc(p.nombre_plan)} · S/ ${p.precio_mensual} · ${esc(p.rate_download)}/${esc(p.rate_upload)}</option>`).join('');
  } catch (err) { avisar(err.message, 'error'); }
}

$('#f-nuevo').onsubmit = async (e) => {
  e.preventDefault();
  const d = Object.fromEntries(new FormData(e.target));
  const cuerpo = { ...d, router_id: +d.router_id, tarifa_id: +d.tarifa_id };
  if (!cuerpo.mac_cliente) delete cuerpo.mac_cliente;       // campos opcionales vacíos no se envían
  if (!cuerpo.fecha_registro) delete cuerpo.fecha_registro;
  try {
    const r = await api('/abonados', 'POST', cuerpo);
    $('#r-nuevo').innerHTML = `<h3>Abonado registrado: ${esc(r.apellidos)}, ${esc(r.nombres)} ${etiqueta(r.estado)}</h3>
      <div class="datos"><b>Id</b><span>${r.id}</span><b>Primer vencimiento</b><span>${fmtFecha(r.fecha_vencimiento)}</span>
      <b>Orden de alta</b><span>${r.orden_alta ? `#${r.orden_alta.id} ${r.orden_alta.accion} (${r.orden_alta.estado})` : '—'}</span>
      <b>Aviso</b><span>${esc(r.aviso || 'Cola simple verificada en el ruteador')}</span></div>`;
    $('#r-nuevo').classList.remove('oculto');
    avisar('Abonado registrado.');
    e.target.reset();
  } catch (err) { avisar(err.message, 'error'); }
};

// ------------------------------------------------------------ 3. Órdenes
async function cargarOrdenes() {
  const est = $('#f-estado').value;
  try {
    const os = await api(`/ordenes${est ? `?estado=${est}` : ''}`);
    tabla('#t-ordenes', ['Orden', 'Abonado', 'Ruteador', 'Acción', 'Estado', 'Intentos', 'Creada'],
      os.map((o) => [o.id, o.cliente_id, o.router_id, esc(o.accion), etiqueta(o.estado), o.intentos, fmtHora(o.fecha_creacion)]));
  } catch (err) { avisar(err.message, 'error'); }
}
$('#b-ordenes').onclick = cargarOrdenes;
$('#f-estado').onchange = cargarOrdenes;
$('#b-despachar').onclick = async () => {
  try {
    const r = await api('/ordenes/despachar', 'POST');
    avisar(`Vuelta ${r.lote}: aplicadas ${r.procesadas.length}, pendientes ${r.pendientes.length}.`);
    cargarOrdenes();
  } catch (err) { avisar(err.message, 'error'); }
};

// ------------------------------------------------------------ 4. Monitoreo (HU-04, HU-05)
let nombresRuteador = {}, nombresEnlace = {};
async function cargarMonitoreo() {
  try {
    const [rs, al, en] = await Promise.all([api('/monitoreo/ruteadores'),
      api(`/monitoreo/alertas?abiertas=${$('#solo-abiertas').checked}`), api('/enlaces')]);
    nombresRuteador = Object.fromEntries(rs.map((r) => [r.id, r.nombre_equipo]));
    nombresEnlace = Object.fromEntries(en.map((e) => [e.id, e.nombre_enlace]));
    $('#ruteadores').innerHTML = rs.map((r) => `<div class="nodo ${r.estado_operativo === 'NODO_CAIDO' ? 'caido' : ''}">
        <div class="nom">${esc(r.nombre_equipo)} ${etiqueta(r.estado_operativo)}</div>
        <div class="det">${esc(r.ip_router)} · bandera ${esc(r.ip_gestion_ospf || '—')}${r.padre_id ? ` · depende de ${esc(nombresRuteador[r.padre_id] || r.padre_id)}` : ''}</div></div>`).join('');
    const origen = (a) => a.enlace_id ? `Enlace ${esc(nombresEnlace[a.enlace_id] || a.enlace_id)}`
      : a.router_id ? esc(nombresRuteador[a.router_id] || `Ruteador ${a.router_id}`) : `Cabecera ${a.master_id}`;
    tabla('#t-alertas', ['Id', 'Tipo', 'Origen', 'Descripción', 'Registro', 'Cierre'],
      al.map((a) => [a.id_alerta, etiqueta(a.prefijo_excepcion), origen(a), `<small>${esc(a.descripcion_error)}</small>`,
        fmtHora(a.fecha_registro), a.fecha_resolucion ? fmtHora(a.fecha_resolucion) : '<span class="estado e-mal">ABIERTA</span>']));
  } catch (err) { avisar(err.message, 'error'); }
}
$('#b-monitoreo').onclick = cargarMonitoreo;
$('#solo-abiertas').onchange = cargarMonitoreo;
$('#b-evaluar').onclick = async () => {
  try {
    const r = await api('/monitoreo/evaluar', 'POST');
    avisar(`Vuelta ${r.vuelta}: caídos ${r.caidos.length}, restablecidos ${r.restablecidos.length}, ` +
      `cabeceras sin respuesta ${r.cabeceras_sin_respuesta.length}, enlaces degradados ${r.enlaces_degradados.length}.`);
    cargarMonitoreo();
  } catch (err) { avisar(err.message, 'error'); }
};

// ------------------------------------------------------------ 5. Enlaces: gráfica de la señal (HU-05)
let enlaces = [], ultimaLectura = null;
async function iniciarEnlaces() {
  try {
    if (!enlaces.length) {
      enlaces = await api('/enlaces');
      $('#sel-enlace').innerHTML = enlaces.map((e) => `<option value="${e.id}">${esc(e.nombre_enlace)}</option>`).join('');
    }
    ultimaLectura = null;
    await actualizarGrafica();
    // tiempo real: consulta cada 10 s; historial: cada 60 s
    temporizador = setInterval(actualizarGrafica, $('#sel-ventana').value.startsWith('u') ? 10000 : 60000);
  } catch (err) { avisar(err.message, 'error'); }
}
$('#sel-enlace').onchange = () => { clearInterval(temporizador); iniciarEnlaces(); };
$('#sel-ventana').onchange = () => { clearInterval(temporizador); iniciarEnlaces(); };

async function actualizarGrafica() {
  const id = $('#sel-enlace').value; if (!id) return;
  const v = $('#sel-ventana').value, tiempoReal = v.startsWith('u');
  const datos = await api(`/enlaces/${id}/lecturas?${tiempoReal ? 'ultimas' : 'horas'}=${v.slice(1)}`);
  const ls = datos.lecturas, nueva = ls.length ? ls[ls.length - 1].fecha_hora : null;
  const desliza = tiempoReal && ultimaLectura && nueva !== ultimaLectura;   // llegó una lectura nueva
  ultimaLectura = nueva;
  dibujar(datos.enlace, ls, tiempoReal, desliza);
  const ult = ls[ls.length - 1];
  $('#estado-grafica').textContent = ult ? `Última lectura: ${ult.rssi_medido} dBm a las ${new Date(ult.fecha_hora).toLocaleTimeString('es-PE')} · umbral ${datos.enlace.rssi_minimo_esperado} dBm`
    : 'Sin lecturas en el periodo';
}

// Dibuja la gráfica en SVG: línea de señal, umbral en rojo y puntos bajo el umbral en rojo.
// En tiempo real el trazo se desplaza a la izquierda cuando entra una lectura nueva (ventana deslizante).
function dibujar(enlace, ls, tiempoReal, desliza) {
  const W = 960, H = 380, m = { i: 60, d: 20, s: 20, b: 50 }, aw = W - m.i - m.d, ah = H - m.s - m.b;
  const umbral = enlace.rssi_minimo_esperado;
  if (!ls.length) { $('#grafica').innerHTML = `<p class="tenue">No hay lecturas de ${esc(enlace.nombre_enlace)} en el periodo elegido.</p>`; return; }
  const vals = ls.map((l) => l.rssi_medido);
  const yMax = Math.ceil(Math.max(umbral + 20, ...vals) / 10) * 10 + 5;   // escala estable con margen
  const yMin = Math.floor(Math.min(umbral - 15, ...vals) / 10) * 10 - 5;
  const y = (v) => m.s + (yMax - v) / (yMax - yMin) * ah;
  const t0 = new Date(ls[0].fecha_hora).getTime(), t1 = new Date(ls[ls.length - 1].fecha_hora).getTime();
  const paso = ls.length > 1 ? aw / (ls.length - 1) : 0;
  const x = (l, i) => tiempoReal || t1 === t0 ? m.i + i * paso : m.i + (new Date(l.fecha_hora).getTime() - t0) / (t1 - t0) * aw;
  let ejeY = '';
  for (let v = Math.ceil(yMin / 10) * 10; v <= yMax; v += 10)
    ejeY += `<line x1="${m.i}" x2="${W - m.d}" y1="${y(v)}" y2="${y(v)}" stroke="#e3e8ef"/><text x="${m.i - 8}" y="${y(v) + 4}" text-anchor="end" font-size="12" fill="#6b7785">${v}</text>`;
  // marcas del eje de tiempo: por lectura en tiempo real; a intervalos iguales de tiempo en el historial
  const marcas = Math.min(ls.length, 6); let ejeX = '';
  for (let k = 0; k < marcas; k++) {
    const ancla = k === 0 ? 'start' : k === marcas - 1 ? 'end' : 'middle';
    let px, f;
    if (tiempoReal || t1 === t0) { const i = Math.round(k * (ls.length - 1) / Math.max(marcas - 1, 1)); px = x(ls[i], i); f = new Date(ls[i].fecha_hora); }
    else { const t = t0 + k * (t1 - t0) / (marcas - 1); px = m.i + (t - t0) / (t1 - t0) * aw; f = new Date(t); }
    const txt = tiempoReal ? f.toLocaleTimeString('es-PE') : f.toLocaleString('es-PE', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
    ejeX += `<text x="${px}" y="${H - m.b + 20}" text-anchor="${ancla}" font-size="12" fill="#6b7785">${txt}</text>`;
  }
  const linea = ls.map((l, i) => `${i ? 'L' : 'M'}${x(l, i).toFixed(1)},${y(l.rssi_medido).toFixed(1)}`).join(' ');
  const puntos = ls.map((l, i) => `<circle cx="${x(l, i)}" cy="${y(l.rssi_medido)}" r="${tiempoReal ? 4 : 2.5}" fill="${l.rssi_medido < umbral ? '#b42318' : '#2f5d8c'}"><title>${l.rssi_medido} dBm · ${new Date(l.fecha_hora).toLocaleString('es-PE')}</title></circle>`).join('');
  const ult = ls[ls.length - 1], xu = x(ult, ls.length - 1), yu = y(ult.rssi_medido);
  $('#grafica').innerHTML = `<h3>${esc(enlace.nombre_enlace)} <span class="tenue">· señal en la antena receptora (${esc(enlace.ip_antena_destino)})</span></h3>
    <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Señal del enlace">
      <defs><clipPath id="zona"><rect x="${m.i - 6}" y="0" width="${aw + 18}" height="${H}"/></clipPath></defs>
      ${ejeY}
      <text x="16" y="${m.s + ah / 2}" transform="rotate(-90 16 ${m.s + ah / 2})" text-anchor="middle" font-size="12" fill="#6b7785">RSSI (dBm)</text>
      <line x1="${m.i}" x2="${W - m.d}" y1="${y(umbral)}" y2="${y(umbral)}" stroke="#b42318" stroke-width="2" stroke-dasharray="6 4"/>
      <text x="${m.i + 6}" y="${y(umbral) + 16}" text-anchor="start" font-size="12" fill="#b42318">Umbral ${umbral} dBm</text>
      <g clip-path="url(#zona)"><g id="trazo" class="desliza" style="transform: translateX(${desliza ? paso : 0}px)">
        <path d="${linea}" fill="none" stroke="#2f5d8c" stroke-width="2.5"/>${puntos}
        <text x="${xu - 8}" y="${yu - 10}" text-anchor="end" font-size="13" font-weight="600" fill="${ult.rssi_medido < umbral ? '#b42318' : '#1b365d'}">${ult.rssi_medido} dBm</text>
      </g></g>
      ${ejeX}
    </svg>`;
  // ventana deslizante: el trazo nuevo empieza un paso a la derecha y se corre a su lugar
  if (desliza) requestAnimationFrame(() => requestAnimationFrame(() => { $('#trazo').style.transform = 'translateX(0)'; }));
}

// ------------------------------------------------------------ 6. Red: mapa de la topología (HU-04, HU-05)
// Árbol de ruteadores (cabecera arriba). Los enlaces inalámbricos se dibujan con línea discontinua y su señal.
// Un ruteador caído o un enlace caído se marcan con una X roja; la cabecera sin respuesta, con una X ámbar.
async function cargarRed() {
  try {
    const t = await api('/consultas/topologia');
    correoActivo = t.correo_activo;
    dibujarRed(t);
    $('#estado-red').textContent = `Estado según el monitoreo · ${new Date(t.generado).toLocaleTimeString('es-PE')}`;
  } catch (err) { avisar(err.message, 'error'); }
}
$('#b-red').onclick = cargarRed;

function dibujarRed(t) {
  const NW = 232, NH = 62, SX = 262, SY = 150, M = 30;
  const hijos = {}; t.nodos.forEach((n) => (hijos[n.padre_id ?? 'raiz'] ||= []).push(n));
  // posición: cada hoja ocupa una columna; el padre se centra sobre sus hijos
  const pos = {}; let col = 0;
  const ubicar = (n, nivel) => {
    const hs = hijos[n.id] || [];
    hs.forEach((h) => ubicar(h, nivel + 1));
    const x = hs.length ? (pos[hs[0].id].x + pos[hs[hs.length - 1].id].x) / 2 : M + NW / 2 + (col++) * SX;
    pos[n.id] = { x, y: M + NH / 2 + nivel * SY };
  };
  (hijos.raiz || []).forEach((r) => ubicar(r, 0));
  const W = Math.max(...Object.values(pos).map((p) => p.x)) + NW / 2 + M, H = Math.max(...Object.values(pos).map((p) => p.y)) + NH / 2 + M + 10;
  const color = (e) => e === 'NODO_CAIDO' || e === 'CAIDO' ? '#b42318' : e === 'CABECERA_INACCESIBLE' || e === 'DEGRADADO' ? '#d98a00' : '#1e7b46';
  const equis = (x, y, c, r = 14) => `<g stroke="${c}" stroke-width="5" stroke-linecap="round"><line x1="${x - r}" y1="${y - r}" x2="${x + r}" y2="${y + r}"/><line x1="${x + r}" y1="${y - r}" x2="${x - r}" y2="${y + r}"/></g>`;
  const radio = (a, b) => t.enlaces.find((e) => (e.origen_id === a && e.destino_id === b) || (e.origen_id === b && e.destino_id === a));
  let lineas = '', nodos = '';
  t.nodos.forEach((n) => {
    if (n.padre_id == null || !pos[n.padre_id]) return;
    const p = pos[n.padre_id], q = pos[n.id], e = radio(n.padre_id, n.id);
    const x1 = p.x, y1 = p.y + NH / 2, x2 = q.x, y2 = q.y - NH / 2, mx = (x1 + x2) / 2, my = (y1 + y2) / 2;
    if (e) {   // enlace inalámbrico: línea discontinua, antena y última señal
      const c = color(e.estado);
      lineas += `<g><title>${esc(e.nombre)} · umbral ${e.umbral} dBm${e.ultima_lectura ? ` · última lectura ${new Date(e.ultima_lectura).toLocaleTimeString('es-PE')}` : ''}${e.alerta ? `\n${esc(e.alerta)}` : ''}</title>
        <line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${c}" stroke-width="3" stroke-dasharray="8 6"/>
        <g transform="translate(${mx - 30},${my - 12})" stroke="${c}" fill="none" stroke-width="2"><line x1="0" y1="18" x2="0" y2="2"/><path d="M-6,4 A8,8 0 0,1 6,4"/><path d="M-10,0 A14,14 0 0,1 10,0"/></g>
        <text x="${mx - 14}" y="${my + 4}" font-size="12" fill="${c}" font-weight="600" stroke="#fff" stroke-width="4" paint-order="stroke">${e.ultima_senal != null ? `${e.ultima_senal} dBm` : 'sin lectura'}</text>
        ${e.estado === 'CAIDO' ? equis(mx + 46, my, '#b42318', 11) : ''}</g>`;
    } else {   // cable o segmento directo
      lineas += `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${n.estado === 'NODO_CAIDO' ? '#b42318' : '#7a8796'}" stroke-width="3"/>`;
    }
  });
  t.nodos.forEach((n) => {
    const { x, y } = pos[n.id] || {}; if (x == null) return;
    const c = color(n.estado), caido = n.estado === 'NODO_CAIDO', muda = n.estado === 'CABECERA_INACCESIBLE';
    nodos += `<g><title>${esc(n.nombre)} · ${esc(n.ip)} · ${n.abonados} abonados${n.alerta ? `\n${esc(n.alerta)}` : ''}</title>
      <rect x="${x - NW / 2}" y="${y - NH / 2}" width="${NW}" height="${NH}" rx="10" fill="${caido ? '#fdecea' : muda ? '#fff4e0' : '#fff'}" stroke="${c}" stroke-width="2.5"/>
      <g transform="translate(${x - NW / 2 + 12},${y - 14})"><rect width="30" height="18" rx="3" fill="${c}"/><circle cx="7" cy="9" r="2" fill="#fff"/><circle cx="14" cy="9" r="2" fill="#fff"/><line x1="8" y1="0" x2="5" y2="-7" stroke="${c}" stroke-width="2"/><line x1="22" y1="0" x2="25" y2="-7" stroke="${c}" stroke-width="2"/></g>
      <text x="${x - NW / 2 + 50}" y="${y - 8}" font-size="12.5" font-weight="600" fill="#1f2933">${esc(n.nombre.length > 25 ? n.nombre.slice(0, 24) + '…' : n.nombre)}</text>
      <text x="${x - NW / 2 + 50}" y="${y + 9}" font-size="11" fill="#6b7785">${esc(n.ip)}</text>
      <text x="${x - NW / 2 + 50}" y="${y + 23}" font-size="11" fill="#6b7785">${n.abonados} abonados${n.en_cascada ? ' · en cascada' : ''}</text>
      ${caido ? equis(x + NW / 2 - 4, y - NH / 2 + 4, '#b42318') : muda ? equis(x + NW / 2 - 4, y - NH / 2 + 4, '#d98a00') : ''}</g>`;
  });
  $('#mapa').innerHTML = `<svg viewBox="0 0 ${W} ${H}" style="max-width:${Math.max(W, 700)}px;margin:auto" role="img" aria-label="Mapa de la red">${lineas}${nodos}</svg>`;
}

// ------------------------------------------------------------ Avisos de avería (en cualquier pestaña)
// Cada 30 s consulta las alertas abiertas: una alerta nueva es una avería y una que desaparece, un
// restablecimiento. El correo lo envía el monitoreo en la misma vuelta que registra o cierra la alerta.
let alertasPrevias = null, correoActivo = false;
async function vigilarAlertas() {
  try {
    if (alertasPrevias === null) correoActivo = (await api('/consultas/topologia')).correo_activo;
    const al = await api('/monitoreo/alertas?abiertas=true');
    const actuales = new Map(al.map((a) => [a.id_alerta, a]));
    if (alertasPrevias) {
      actuales.forEach((a, id) => { if (!alertasPrevias.has(id)) notificar(a, false); });
      alertasPrevias.forEach((a, id) => { if (!actuales.has(id)) notificar(a, true); });
      if ([...actuales.keys()].some((id) => !alertasPrevias.has(id)) || [...alertasPrevias.keys()].some((id) => !actuales.has(id))) {
        if (!$('#p-red').classList.contains('oculto')) cargarRed();
        if (!$('#p-monitoreo').classList.contains('oculto')) cargarMonitoreo();
      }
    }
    alertasPrevias = actuales;
  } catch (err) { /* sin conexión con la API: se reintenta en la siguiente consulta */ }
}

function notificar(a, restablecida) {
  const n = document.createElement('div');
  n.className = `notif ${restablecida ? 'ok' : ''}`;
  const correo = correoActivo ? (restablecida ? '✉ Correo de restablecimiento enviado al personal técnico' : '✉ Correo de avería enviado al personal técnico')
    : 'Envío de correos desactivado (ALERTA_CORREO)';
  n.innerHTML = `<span class="cerrar" title="Cerrar">✕</span><b>${restablecida ? 'Restablecido' : 'Avería detectada'} · ${esc(a.prefijo_excepcion)}</b>
    ${esc(a.descripcion_error.split('\n')[0].slice(0, 160))}<div class="correo">${correo}</div>`;
  n.querySelector('.cerrar').onclick = () => n.remove();
  $('#notificaciones').appendChild(n);
  setTimeout(() => n.remove(), 20000);
}

vigilarAlertas();
setInterval(vigilarAlertas, 30000);
abrirPestana('abonados');
