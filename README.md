# Cofactor 3D Builder

**A no-code tool that turns a cofactor or ligand into a docking-ready 3D structure (SDF + PDB).**

Type a name such as *FAD*, *NADPH* or *hexadecane*, paste a SMILES, or upload a 2D file. The tool builds and energy-minimises a 3D structure with [RDKit](https://www.rdkit.org/) and saves it for PyRx, AutoDock Vina or any other docking program. It runs in your web browser, on your own computer, and needs no coding.

![Cofactor 3D Builder screenshot](docs/screenshot.png)

## 🚀 Quick start (Windows, 3 steps, no coding)

| Step | What to do | How often |
|---|---|---|
| **1** | Install **Python** from [python.org/downloads](https://www.python.org/downloads/). ⚠️ On the first installer screen, **tick "Add python.exe to PATH"**. | once |
| **2** | **[⬇️ Download the tool (ZIP)](https://github.com/viduminialwis/cofactor-3d-builder/archive/refs/heads/main.zip)**, right-click the ZIP and choose **Extract All**, then open the folder and double-click **`Install first time.bat`**. Wait until it says *Done!* | once |
| **3** | Double-click **`Start Cofactor 3D.bat`**. The tool opens in your web browser. | every time |

Keep the black window open while you use the tool, and close it when you have finished. Your 3D files are saved in **`Documents\Ligands_3D`**.

Something not working? See [Troubleshooting](#troubleshooting).

## Why this tool?

Building 3D ligands from SMILES with a script is quick, but it is easy to get wrong without noticing:

- **Missing stereochemistry.** If a SMILES has no `@`/`@@`, RDKit picks the stereocentres at random. For cofactors like FAD or NAD(P)H you can end up docking an L-sugar or a mixed isomer, and the formula still looks correct. **This tool stops and warns you** when stereocentres are undefined.
- **Wrong redox form or tautomer.** For example, a hand-written "FADH2" SMILES can be a 4a,5-dihydro tautomer instead of the true 1,5-dihydroflavin. Fetching the structure from **PubChem by name** avoids this, and the tool shows the PubChem CID so you can check it.
- **One random conformer.** The tool builds several conformers and keeps the lowest-energy one, with a fixed random seed so every run is reproducible.
- **Poor record keeping.** Every run is logged (SMILES, seed, force field, energy) in a CSV file, so you can write your Methods section later.

## Features

- Three input options: **search by name** (PubChem), **paste SMILES**, or **upload** `.sdf` / `.mol` / `.mol2` / `.smi` files
- Quick-pick buttons for common cofactors (FAD, FADH2, FMN, FMNH2, NAD⁺, NADH, NADP⁺, NADPH, CoA) and n-alkanes (n-C16, n-C22, n-C28)
- Guard against undefined stereochemistry, which you can override for achiral molecules such as alkanes
- Removal of salts and water: only the largest fragment is kept
- Interactive 3D preview in the browser ([3Dmol.js](https://3dmol.csb.pitt.edu/))
- Output as **SDF** (keeps bond orders; recommended for PyRx) and **PDB** (with a residue code you choose)
- Optional multi-conformer SDF for ensemble docking
- `generation_log.csv` recording every structure you make

## Installation on Mac / Linux

Open a Terminal inside the downloaded folder and run:

```bash
pip install -r requirements.txt
python cofactor3d_app.py
```

The tool opens in your browser. If it doesn't, go to <http://127.0.0.1:8765>.

## How to use

1. **Choose your molecule.** Search by name, paste a SMILES or upload a file. When searching by name, open the PubChem link and check that it is the form you want, for example oxidised vs reduced.
2. **Name it**, and optionally set a 3-letter PDB residue code (e.g. `FAD`, `FDA`, `NDP`).
3. Click **Make 3D structure**. Check the 3D preview, then use the **SDF** file for docking.

Files are saved to `Documents\Ligands_3D` by default. To change this, create a `settings.json` file next to `cofactor3d_app.py`:

```json
{"output_folder": "D:\\My project\\Docking\\Ligands_3D"}
```

## Method

1. The input is parsed with RDKit. Only the largest fragment is kept, and undefined tetrahedral or double-bond stereocentres are detected; phosphorus and sulfur centres are ignored.
2. Hydrogens are added, and *n* conformers (default 10) are embedded with **ETKDGv3** (random seed 42 by default).
3. Each conformer is optimised with **MMFF94**, or UFF if MMFF94 parameters are missing.
4. The **lowest-energy conformer** is written as SDF and PDB.

Example Methods sentence (please adapt it to your settings):

> Three-dimensional structures of the cofactors were obtained from PubChem isomeric SMILES and generated with RDKit (version X) using the ETKDGv3 algorithm (10 conformers, random seed 42), followed by MMFF94 geometry optimisation. The lowest-energy conformer was used for docking.

## Limitations

- **Metal-containing cofactors** (heme, Fe–S clusters, di-iron centres) cannot be built reliably. Take them from an experimental structure in the [PDB](https://www.rcsb.org/).
- **Protonation state:** PubChem SMILES are usually neutral (e.g. phosphates drawn as –OH). The tool does not protonate for a particular pH, so prepare the charge state in your docking software if you need to, and report it.
- A single minimised gas-phase conformer is a starting point. Docking programs such as Vina still treat rotatable bonds as flexible.
- The name search needs internet access to PubChem; the 3D preview needs internet to load 3Dmol.js. Building and saving work offline with SMILES or files.

## Troubleshooting

| Problem | Solution |
|---|---|
| *"Python was not found"* | Install Python (Quick start step 1) and make sure **"Add python.exe to PATH"** is ticked. If you already installed it without ticking, run the installer again, choose **Modify**, and tick it. |
| The black window says *"No module named rdkit"* | Run **`Install first time.bat`** first, and check that it ends with *Done!* |
| Windows shows *"Windows protected your PC"* | Click **More info**, then **Run anyway**. The `.bat` files are plain text, and you can open them in Notepad to see exactly what they do. |
| The browser did not open | Leave the black window open, and type <http://127.0.0.1:8765> in your browser's address bar. |
| *"Lost contact with the tool"* on the web page | The black window was closed. Double-click `Start Cofactor 3D.bat` again. |
| *"Could not reach PubChem"* | Check your internet connection and try again in a minute (PubChem is sometimes busy), or paste the SMILES instead. |
| The tool refuses because of *undefined stereocentres* | This protects you from docking a random isomer. Use **Search by name**, or copy the SMILES from PubChem. For molecules without stereocentres (e.g. alkanes), tick **Advanced settings → Allow undefined stereo**. |
| No 3D preview appears | The preview needs internet. Your SDF/PDB files are still created. |
| Something else | The error is saved in `error_log.txt` in the tool folder. Please [open an issue](https://github.com/viduminialwis/cofactor-3d-builder/issues) and attach it. |

## Citation

If this tool helps your research, please cite it using the **"Cite this repository"** button on this page (see [`CITATION.cff`](CITATION.cff)). Please also cite RDKit.

## Author

**Vidumini Alwis**, MPhil researcher, Department of Zoology and Environment Sciences, University of Colombo, Sri Lanka · ORCID [0009-0004-6155-2295](https://orcid.org/0009-0004-6155-2295)

Developed with the help of Claude (Anthropic) as an AI coding assistant.

## License

[MIT](LICENSE): free to use, modify and share, with attribution.
