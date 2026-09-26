"""
Cofactor 3D Builder - a small local web page that turns a cofactor/ligand
(name, SMILES or 2D file) into a 3D structure (SDF + PDB) for docking.

Method:
  RDKit ETKDGv3 embedding of several conformers (fixed random seed)
  -> MMFF94 optimisation (UFF fallback) -> lowest-energy conformer is saved.

Run by double-clicking "Start Cofactor 3D.bat". Nothing to install beyond RDKit.
Optional: create settings.json next to this file, e.g.
  {"output_folder": "D:\\My project\\Docking\\Ligands_3D"}
to change where files are saved (default: Documents\\Ligands_3D).
"""

import csv
import datetime as dt
import io
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from html import escape as html_escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import rdkit
from rdkit import Chem, RDLogger
from rdkit.Chem import AllChem, Descriptors, rdMolDescriptors
from rdkit.Chem.MolStandardize import rdMolStandardize

RDLogger.DisableLog("rdApp.*")

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUT = os.path.join(os.path.expanduser("~"), "Documents", "Ligands_3D")
try:  # personal output folder, kept out of the shared code
    with open(os.path.join(HERE, "settings.json"), encoding="utf-8") as _fh:
        _custom = json.load(_fh).get("output_folder", "")
    if _custom and os.path.isdir(os.path.dirname(_custom.rstrip("\\/"))):
        DEFAULT_OUT = _custom
except (OSError, ValueError):
    pass


# ---------------------------------------------------------------- PubChem
def fetch_json(url):
    """GET a JSON URL. PubChem sometimes refuses Python's HTTPS client (HTTP 503)
    while accepting Windows PowerShell, so fall back to PowerShell on Windows."""
    try:
        with urllib.request.urlopen(url, timeout=25) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        if e.code in (400, 404) or os.name != "nt":
            raise
    except (urllib.error.URLError, socket.timeout):
        if os.name != "nt":
            raise
    ps = ("$ProgressPreference='SilentlyContinue'; try { [Console]::OutputEncoding=[Text.Encoding]::UTF8; "
          f"(Invoke-WebRequest -UseBasicParsing -TimeoutSec 25 -Uri '{url}').Content }} "
          "catch { $c = [int]$_.Exception.Response.StatusCode; Write-Output ('HTTPERROR ' + $c) }")
    out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                         capture_output=True, text=True, encoding="utf-8", timeout=60,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.strip()
    if out.startswith("HTTPERROR"):
        code = int(out.split()[1] or 0)
        raise urllib.error.HTTPError(url, code, "PubChem error", None, None)
    return json.loads(out)


def pubchem_lookup(name):
    """Return dict with cid, title, formula, smiles for a compound name."""
    q = urllib.parse.quote(name.strip(), safe="")
    base = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/" + q + "/property/"
    last_err = "unknown error"
    # PubChem renamed IsomericSMILES -> SMILES in 2025; try both.
    for props in ("SMILES,MolecularFormula,Title", "IsomericSMILES,MolecularFormula,Title"):
        for attempt in range(4):
            try:
                data = fetch_json(base + props + "/JSON")
                p = data["PropertyTable"]["Properties"][0]
                smi = p.get("SMILES") or p.get("IsomericSMILES")
                if not smi:
                    break
                return {
                    "cid": p.get("CID"),
                    "title": p.get("Title", name),
                    "formula": p.get("MolecularFormula", ""),
                    "smiles": smi,
                }
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    raise ValueError(f'PubChem has no compound called "{name}". '
                                     "Try another name (e.g. the full name) or paste the SMILES.")
                if e.code == 400:
                    last_err = "bad request"
                    break  # try the other property name
                last_err = f"PubChem is busy (HTTP {e.code})"
                time.sleep(1.5 * (attempt + 1))
            except (urllib.error.URLError, socket.timeout) as e:
                last_err = f"no internet connection to PubChem ({e})"
                time.sleep(1.5 * (attempt + 1))
    raise ValueError(f"Could not reach PubChem: {last_err}. Wait a minute and try again, "
                     "or paste the SMILES instead.")


# ---------------------------------------------------------------- parsing
def parse_input(kind, text, filename=""):
    """Turn user input into an RDKit molecule (no hydrogens yet)."""
    text = text or ""  # no strip(): line 1 of a MOL/SDF block (the name) may be blank
    if not text.strip():
        raise ValueError("Nothing to convert. Please enter a SMILES, a name, or choose a file.")
    ext = os.path.splitext(filename.lower())[1]

    if kind == "file" and ext in (".sdf", ".mol", ".sd"):
        sup = Chem.ForwardSDMolSupplier(io.BytesIO(text.encode()), removeHs=False)
        mol = next((m for m in sup if m is not None), None)
        if mol is not None and mol.GetNumConformers() and mol.GetConformer().Is3D():
            Chem.AssignStereochemistryFrom3D(mol)
    elif kind == "file" and ext == ".mol2":
        mol = Chem.MolFromMol2Block(text, removeHs=False)
    elif kind == "file" and ext == ".pdb":
        raise ValueError("PDB files do not store bond orders, so the structure can be read wrongly. "
                         "Please use SDF, MOL, MOL2 or a SMILES instead.")
    else:  # SMILES (typed, from PubChem, or a .smi/.txt file)
        first = next((ln for ln in text.splitlines() if ln.strip()), "")
        smi = first.split()[0]
        mol = Chem.MolFromSmiles(smi)
        if mol is None:
            raise ValueError("RDKit could not read this SMILES. Check for typing mistakes "
                             "(copy it directly from PubChem to be safe).")
        return mol

    if mol is None:
        raise ValueError("Could not read this file. Check that it is a valid SDF/MOL/MOL2 file.")
    return Chem.RemoveHs(mol, sanitize=True)


def stereo_report(mol):
    """Count undefined stereocentres (ignoring P/S, e.g. phosphates) and double bonds."""
    atoms, bonds = [], 0
    for si in Chem.FindPotentialStereo(mol):
        if si.specified != Chem.StereoSpecified.Unspecified:
            continue
        if si.type == Chem.StereoType.Atom_Tetrahedral:
            a = mol.GetAtomWithIdx(si.centeredOn)
            if a.GetSymbol() not in ("P", "S"):
                atoms.append(si.centeredOn)
        elif si.type == Chem.StereoType.Bond_Double:
            bonds += 1
    return atoms, bonds


def safe_name(s):
    s = re.sub(r"[^A-Za-z0-9_+\-]+", "_", s.strip()).strip("_")
    return s[:60] or "ligand"


# ---------------------------------------------------------------- 3D build
def build_3d(req):
    warnings = []
    mol = parse_input(req.get("kind"), req.get("text"), req.get("filename", ""))

    # keep only the largest piece (drops Na+, Cl-, water from salts)
    if len(Chem.GetMolFrags(mol)) > 1:
        mol = rdMolStandardize.LargestFragmentChooser().choose(mol)
        warnings.append("The input had several pieces (e.g. a salt such as Na+ or a water). "
                        "Only the largest piece was kept.")

    input_smiles = Chem.MolToSmiles(mol)
    bad_atoms, bad_bonds = stereo_report(mol)
    if (bad_atoms or bad_bonds) and not req.get("allow_undefined"):
        parts = []
        if bad_atoms:
            parts.append(f"{len(bad_atoms)} stereocentre(s)")
        if bad_bonds:
            parts.append(f"{len(bad_bonds)} double bond(s)")
        raise ValueError(
            "STEREO: This structure has " + " and ".join(parts) + " with no defined 3D "
            "arrangement (no @ / @@ in the SMILES). RDKit would choose them at random, so the "
            "3D model could be the wrong isomer (for example L-ribose instead of D-ribose). "
            "Fix: use the 'Search by name' tab, or copy the SMILES from PubChem, which includes "
            "the stereochemistry. If you are sure this is fine (e.g. an alkane), tick "
            "'Allow undefined stereo' and press the button again.")
    if bad_atoms or bad_bonds:
        warnings.append(f"{len(bad_atoms)} undefined stereocentre(s) were assigned at random "
                        "(you allowed this).")

    mol_h = Chem.AddHs(mol)
    n_conf = max(1, min(int(req.get("n_conf", 10)), 100))
    seed = int(req.get("seed", 42))

    params = AllChem.ETKDGv3()
    params.randomSeed = seed
    params.numThreads = 0
    cids = list(AllChem.EmbedMultipleConfs(mol_h, numConfs=n_conf, params=params))
    if not cids:  # difficult molecules: start from random coordinates
        params.useRandomCoords = True
        cids = list(AllChem.EmbedMultipleConfs(mol_h, numConfs=n_conf, params=params))
    if not cids:
        raise ValueError("RDKit could not build a 3D shape for this molecule. Metal-containing "
                         "cofactors (heme, Fe-S clusters, di-iron centres) usually fail. For those, "
                         "take the cofactor from a crystal structure in the PDB instead.")

    # optimise every conformer, keep the lowest energy
    ff_name = "none"
    energies = {}
    if AllChem.MMFFHasAllMoleculeParams(mol_h):
        ff_name = "MMFF94"
        res = AllChem.MMFFOptimizeMoleculeConfs(mol_h, numThreads=0, maxIters=5000)
        energies = {cid: e for cid, (conv, e) in zip(cids, res)}
    elif AllChem.UFFHasAllMoleculeParams(mol_h):
        ff_name = "UFF"
        warnings.append("MMFF94 has no parameters for this molecule, so UFF was used instead.")
        res = AllChem.UFFOptimizeMoleculeConfs(mol_h, numThreads=0, maxIters=5000)
        energies = {cid: e for cid, (conv, e) in zip(cids, res)}
    else:
        warnings.append("No force field could handle this molecule; the geometry was NOT "
                        "optimised. Check the structure carefully before docking.")
        energies = {cid: 0.0 for cid in cids}
    best = min(energies, key=energies.get)

    # names for files and PDB residue
    name = req.get("name") or req.get("title") or "ligand"
    fname = safe_name(name)
    resname = (re.sub(r"[^A-Za-z0-9]", "", req.get("resname") or "LIG").upper() or "LIG")[:3]
    counts = {}
    for atom in mol_h.GetAtoms():
        el = atom.GetSymbol()
        counts[el] = counts.get(el, 0) + 1
        info = Chem.AtomPDBResidueInfo()
        label = f"{el}{counts[el]}"
        info.SetName(f" {label}".ljust(4) if len(el) == 1 and len(label) <= 3 else label[:4].ljust(4))
        info.SetResidueName(resname)
        info.SetResidueNumber(1)
        info.SetIsHeteroAtom(True)
        atom.SetMonomerInfo(info)

    mol_h.SetProp("_Name", name)
    mol_h.SetProp("SMILES_input", input_smiles)
    mol_h.SetProp("Method", f"RDKit {rdkit.__version__} ETKDGv3 ({len(cids)} conformers, seed {seed}) + {ff_name}")
    mol_h.SetProp("Energy_kcal_per_mol", f"{energies[best]:.3f}")

    sdf_buf = io.StringIO()
    w = Chem.SDWriter(sdf_buf)
    w.write(mol_h, confId=best)
    w.close()
    sdf = sdf_buf.getvalue()
    pdb = Chem.MolToPDBBlock(mol_h, confId=best)

    all_sdf = None
    if req.get("save_all"):
        order = sorted(energies, key=energies.get)
        buf = io.StringIO()
        w = Chem.SDWriter(buf)
        for rank, cid in enumerate(order, 1):
            mol_h.SetProp("_Name", f"{name}_conf{rank}")
            mol_h.SetProp("Energy_kcal_per_mol", f"{energies[cid]:.3f}")
            w.write(mol_h, confId=cid)
        w.close()
        all_sdf = buf.getvalue()

    # save to disk
    saved = []
    out_dir = (req.get("out_dir") or DEFAULT_OUT).strip().strip('"')
    if req.get("save", True):
        os.makedirs(out_dir, exist_ok=True)
        for ext, content in (("sdf", sdf), ("pdb", pdb)):
            p = os.path.join(out_dir, f"{fname}.{ext}")
            with open(p, "w", newline="\n") as fh:
                fh.write(content)
            saved.append(p)
        if all_sdf:
            p = os.path.join(out_dir, f"{fname}_all_conformers.sdf")
            with open(p, "w", newline="\n") as fh:
                fh.write(all_sdf)
            saved.append(p)
        log = os.path.join(out_dir, "generation_log.csv")
        new = not os.path.exists(log)
        with open(log, "a", newline="", encoding="utf-8") as fh:
            cw = csv.writer(fh)
            if new:
                cw.writerow(["date_time", "name", "source", "pubchem_cid", "input_smiles", "formula",
                             "rdkit_version", "embedding", "conformers", "random_seed",
                             "force_field", "best_energy_kcal_mol", "undefined_stereo", "files"])
            cw.writerow([dt.datetime.now().strftime("%Y-%m-%d %H:%M"), name, req.get("kind"),
                         req.get("cid") or "", input_smiles, rdMolDescriptors.CalcMolFormula(mol),
                         rdkit.__version__, "ETKDGv3", len(cids), seed, ff_name,
                         f"{energies[best]:.3f}", len(bad_atoms) + bad_bonds,
                         "; ".join(os.path.basename(s) for s in saved)])

    return {
        "ok": True,
        "name": name,
        "file_stem": fname,
        "sdf": sdf,
        "pdb": pdb,
        "all_sdf": all_sdf,
        "saved": saved,
        "out_dir": out_dir,
        "warnings": warnings,
        "info": {
            "Formula": rdMolDescriptors.CalcMolFormula(mol),
            "Molecular weight": f"{Descriptors.MolWt(mol):.2f} g/mol",
            "Heavy atoms / total atoms": f"{mol.GetNumHeavyAtoms()} / {mol_h.GetNumAtoms()}",
            "Net formal charge": str(Chem.GetFormalCharge(mol)),
            "Rotatable bonds": str(rdMolDescriptors.CalcNumRotatableBonds(mol)),
            "Conformers built": str(len(cids)),
            "Force field": ff_name,
            "Best energy": f"{energies[best]:.2f} kcal/mol",
            "Random seed": str(seed),
            "SMILES used": input_smiles,
        },
    }


# ---------------------------------------------------------------- web server
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        port = self.server.server_address[1]
        if self.headers.get("Host", "") not in {f"127.0.0.1:{port}", f"localhost:{port}"}:
            return self._send(403, "{}")
        if self.path.split("?")[0] in ("/", "/index.html"):
            with open(os.path.join(HERE, "index.html"), encoding="utf-8") as fh:
                html = fh.read().replace("__DEFAULT_OUT__", html_escape(DEFAULT_OUT))
            self._send(200, html, "text/html")
        else:
            self._send(404, "{}")

    def _from_own_page(self):
        """Only accept requests from this tool's own page. Blocks other websites open in
        the same browser from calling the tool (cross-site requests, DNS rebinding)."""
        port = self.server.server_address[1]
        allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if self.headers.get("Host", "") not in allowed:
            return False
        origin = self.headers.get("Origin")
        if origin and origin not in {"http://" + h for h in allowed}:
            return False
        # a JSON content type forces browsers to ask permission (CORS preflight) first
        return self.headers.get("Content-Type", "").startswith("application/json")

    def do_POST(self):
        if not self._from_own_page():
            return self._send(403, json.dumps({"ok": False, "error": "Request refused."}))
        try:
            n = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(n).decode() or "{}")
            if self.path == "/api/lookup":
                out = pubchem_lookup(req.get("name", ""))
            elif self.path == "/api/generate":
                out = build_3d(req)
            elif self.path == "/api/open":
                path = req.get("path") or DEFAULT_OUT
                os.makedirs(path, exist_ok=True)
                if os.name == "nt":
                    os.startfile(path)
                else:
                    subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", path])
                out = {"ok": True}
            else:
                return self._send(404, "{}")
            self._send(200, json.dumps(out))
        except Exception as e:  # show every problem in the page, in plain words
            self._send(200, json.dumps({"ok": False, "error": str(e)}))


def free_port(start=8765):
    for port in range(start, start + 50):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise RuntimeError("No free port found")


def main():
    port = free_port()
    url = f"http://127.0.0.1:{port}/"
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print("=" * 60)
    print("  Cofactor 3D Builder is running")
    print(f"  Open this in your browser:  {url}")
    print(f"  Files are saved to: {DEFAULT_OUT}")
    print("  Keep this window open while you work. Close it to stop.")
    print("=" * 60)
    if not os.environ.get("C3D_NO_BROWSER"):
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        err = traceback.format_exc()
        with open(os.path.join(HERE, "error_log.txt"), "a", encoding="utf-8") as fh:
            fh.write(f"--- {dt.datetime.now():%Y-%m-%d %H:%M:%S}\n{err}\n")
        print(err)
        raise SystemExit(1)
