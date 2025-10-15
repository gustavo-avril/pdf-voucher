# app.py
import os, logging, zipfile, io, tempfile, pathlib
import re
import io
import uuid
from pypdf import PdfReader
import pdfkit
import zipfile
from flask import Flask, request, render_template, send_file, flash, redirect, after_this_request

# ---------- config ----------
BASE   = pathlib.Path(__file__).parent
UPLOAD = BASE / 'tmp' / 'upload'
OUTPUT = BASE / 'tmp' / 'output'
ALLOWED = {'pdf'}
os.makedirs(UPLOAD, exist_ok=True)
os.makedirs(OUTPUT, exist_ok=True)

for p in (UPLOAD, OUTPUT):
    p.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.secret_key = '3f8a2e5b9c1d4e6f8a0b2c4d6e8f0a1b'

TEMPLATE_MAP = {
    'INFINITY25':               'inf25pro.html',
    'INFINITY40':               'inf40pro.html',
    'INFINITY60':               'inf60pro.html',
    'INFINITY80':               'inf80pro.html',
    'INFINITYEUROP40PROTECT':   'inf40EUpro.html',
    'PREMIUM60PROTECT':         'pre60pro.html',
    'PREMIUM80PROTECT':         'pre80pro.html',
    'PREMIUM100PROTECT':        'pre100pro.html',
    'PREMIUM150PROTECT':        'pre150pro.html',
    'PREMIUM250PROTECT':        'pre250pro.html',
    'PREMIUMEUROP50PROTECT':    'pre50proEU.html',
}

# ---------- helpers ----------
def _safe_remove(path):
    try:
        os.remove(path)
    except Exception as e:
        logging.warning("No se pudo borrar %s : %s", path, e)


def build_zip(pdf_paths, safe_names):
    """
    pdf_paths  – list of absolute paths to the finished PDFs
    safe_names – list of clean client-side names  (John Doe-EN.pdf …)
    returns a BytesIO zip file
    """
    mem_zip = io.BytesIO()
    with zipfile.ZipFile(mem_zip, mode='w', compression=zipfile.ZIP_DEFLATED) as zf:
        for file_path, nice_name in zip(pdf_paths, safe_names):
            zf.write(file_path, arcname=nice_name)
    mem_zip.seek(0)
    return mem_zip

def allowed_file(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED

def extract_fields(path: str) -> dict:
    reader = PdfReader(path)
    text   = reader.pages[0].extract_text() or ""
    lines  = text.splitlines()

    data = {}

    # regex por campo (multilínea, sin re.S)
    voucher_re = re.compile(r"VOUCHER\s*N[º°]?\s*:\s*(?P<VOUCHER>\d+)", re.I)
    nombre_re  = re.compile(r"APELLIDO\s*y\s*NOMBRE\s*:\s*(?P<APELLIDO_NOMBRE>.*?)$", re.I)
    id_re      = re.compile(r"(?:DNI|PASAPORTE)\s*(?:N[º°]?:)?\s*(?P<DNI>[\w\d\.]+)", re.I)
    fnac_re    = re.compile(r"FECHA\s*DE\s*NACIMIENTO\s*:\s*(?P<FECHA_NACIMIENTO>[\d/]+)", re.I)
    plan_re    = re.compile(r"PLAN\s*:\s*(?P<PLAN>[^\n]+)", re.I)          # captura todo el plan
    dest_re    = re.compile(r"DESTINO\s*:\s*(?P<DESTINO>\w+)", re.I)
    vig_re     = re.compile(r"VIGENCIA\s*:.*?DEL\s*(?P<VIGENCIA_DEL>[\d/]+)\s*AL\s*(?P<VIGENCIA_AL>[\d/]+)", re.I)
    emi_re     = re.compile(r"FECHA\s*DE\s*EMISION\s*:\s*(?P<FECHA_EMISION>[\d/]+)", re.I)
    emer_re    = re.compile(r"CONTACTO\s*EMERGENCIA\s*:\s*(?P<CONTACTO_EMERGENCIA>.*?)$", re.I)
    tel_re     = re.compile(r"TEL\.?\s*:\s*(?P<TEL>\S.*)", re.I)
    age_re     = re.compile(r"AGENCIA\s*:\s*(?P<AGENCIA>[^\n]+)", re.I)

    # búsqueda línea a línea
    for line in lines:
        if not data.get("VOUCHER"):
            m = voucher_re.search(line)
            if m: data["VOUCHER"] = m.group("VOUCHER"); continue
        if not data.get("APELLIDO_NOMBRE"):
            m = nombre_re.search(line)
            if m: data["APELLIDO_NOMBRE"] = m.group("APELLIDO_NOMBRE").strip(" ,."); continue
        if not data.get("DNI"):
          m = id_re.search(line)
          if m: data["DNI"] = m.group("DNI"); continue
        if not data.get("FECHA_NACIMIENTO"):
            m = fnac_re.search(line)
            if m: data["FECHA_NACIMIENTO"] = m.group("FECHA_NACIMIENTO"); continue
        if not data.get("PLAN"):
            m = plan_re.search(line)
            if m: data["PLAN"] = m.group("PLAN").strip(); continue
        if not data.get("DESTINO"):
            m = dest_re.search(line)
            if m: data["DESTINO"] = m.group("DESTINO"); continue
        if not data.get("VIGENCIA_DEL"):
            m = vig_re.search(line)
            if m:
                data["VIGENCIA_DEL"] = m.group("VIGENCIA_DEL")
                data["VIGENCIA_AL"]  = m.group("VIGENCIA_AL")
                continue
        if not data.get("FECHA_EMISION"):
            m = emi_re.search(line)
            if m: data["FECHA_EMISION"] = m.group("FECHA_EMISION"); continue
        if not data.get("CONTACTO_EMERGENCIA"):
            m = emer_re.search(line)
            if m:
                data["CONTACTO_EMERGENCIA"] = m.group("CONTACTO_EMERGENCIA").strip()
                continue
        if not data.get("TEL"):
            m = tel_re.search(line)
            if m: data["TEL"] = m.group("TEL"); continue
        if not data.get("AGENCIA"):
            m = age_re.search(line)
            if m: data["AGENCIA"] = m.group("AGENCIA").strip(); continue

    # validación
    required = {"VOUCHER", "APELLIDO_NOMBRE", "DNI", "PLAN", "DESTINO",
                "VIGENCIA_DEL", "VIGENCIA_AL", "FECHA_EMISION",
                "CONTACTO_EMERGENCIA", "TEL", "AGENCIA"}
    if not required.issubset(data):
        missing = required - data.keys()
        raise ValueError(f"Faltan campos: {missing}")
    return data

def plan_to_template(plan_field: str) -> str:
    plan = plan_field.upper().replace("-", "").replace(" ", "")
    for key, tpl in TEMPLATE_MAP.items():
        if key.upper() in plan:
            return tpl
    return 'inf25pro.html'

# ---------- NEW route ----------
@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        uploaded_files = request.files.getlist('pdf')   # ← list of FileStorage
        if not uploaded_files or any(f.filename == '' for f in uploaded_files):
            flash('Selecciona al menos un archivo PDF')
            return redirect(request.url)

        out_files   = []   # absolute paths to finished PDFs
        dl_names    = []   # pretty names for the zip
        tmp_path_list = [] # paths to original uploads (to delete later)

        for file in uploaded_files:
            if not allowed_file(file.filename):
                flash(f'{file.filename} no es un PDF')
                continue

            tmp_path = os.path.join(UPLOAD, uuid.uuid4().hex + '.pdf')
            file.save(tmp_path)
            tmp_path_list.append(tmp_path)          # ← guardamos para borrar

            try:
                data     = extract_fields(tmp_path)
                template = plan_to_template(data['PLAN'])
            except Exception as e:
                flash(f'Error procesando {file.filename}: {e}')
                continue

            html      = render_template(template, **data)
            out_path  = os.path.join(OUTPUT, uuid.uuid4().hex + '.pdf')
            pdfkit.from_string(html, out_path)

            safe = re.sub(r'[^a-zA-Z0-9 ,()-]', '', data["APELLIDO_NOMBRE"]).strip()
            dl_names.append(f'{safe}-EN.pdf')
            out_files.append(out_path)

        if not out_files:          # nada se procesó
            return redirect(request.url)

        # --------- single file ---------
        if len(out_files) == 1:
            up_path   = tmp_path_list[0]
            out_path  = out_files[0]
            nice_name = dl_names[0]

            @after_this_request
            def cleanup_single(response):
                _safe_remove(up_path)
                _safe_remove(out_path)
                return response

            return send_file(out_path,
                           as_attachment=True,
                           download_name=nice_name)

        # --------- multiple files → zip ---------
        zip_blob = build_zip(out_files, dl_names)

        @after_this_request
        def cleanup_multi(response):
            for p in tmp_path_list:
                _safe_remove(p)
            for p in out_files:
                _safe_remove(p)
            return response

        return send_file(zip_blob,
                       as_attachment=True,
                       download_name='vouchers_traducidos.zip',
                       mimetype='application/zip')

    return render_template('index.html')

if __name__ == '__main__':
    # Local → debug, Producción → gunicorn
    app.run(debug=True)