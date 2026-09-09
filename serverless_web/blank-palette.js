const SWATCH_NAMES = [
  "Light-Gray", "Black", "Blue", "Red", "Green", "Yellow", "Orange", "Cyan",
  "Magenta", "Dark-Blue", "Dark-Red", "Dark-Green", "Dark-Yellow", "Dark-Orange",
  "Light-Blue", "Dark-Magenta", "Medium-Gray", "Slate-Blue", "Rose",
  "Periwinkle-Blue", "Raspberry", "Sage-Green", "Peach", "Light-Pink",
  "Orchid-Pink", "Deep-Purple", "Rust-Brown", "Teal", "Bright-Mint-Green",
  "Light-Gold", "Labels", "Holographic"
];

const PLACEHOLDER_VALUES = {
  index: 0,
  name: "",
  LinkPath: null,
  minPower: 0,
  maxPower: 0,
  maxPower2: 0,
  speed: 0,
  frequency: 0,
  QPulseWidth: 0,
  interval: 0,
  angle: 0,
  anglePerPass: 0,
  crossHatch: 0,
  doOutput: 0,
  hide: 1,
  numPasses: 1,
};

function buildBlankPaletteXml(materialName) {
  const documentXml = document.implementation.createDocument("", "LightBurnLibrary", null);
  const root = documentXml.documentElement;
  root.setAttribute("RasterizerTemplate", "UNCONFIGURED");
  root.setAttribute("Warning", "PLACEHOLDERS_ONLY_DO_NOT_RUN");
  const material = documentXml.createElement("Material");
  material.setAttribute("name", materialName);
  root.append(material);

  for (const swatchName of SWATCH_NAMES) {
    const entry = documentXml.createElement("Entry");
    entry.setAttribute("Thickness", "-1.0000");
    entry.setAttribute("Desc", `UNCONFIGURED ${swatchName}`);
    const cut = documentXml.createElement("CutSetting");
    cut.setAttribute("type", "Scan");
    for (const [field, configuredValue] of Object.entries(PLACEHOLDER_VALUES)) {
      const element = documentXml.createElement(field);
      const value = field === "LinkPath"
        ? `${materialName}/-1.0000/UNCONFIGURED ${swatchName}`
        : configuredValue;
      element.setAttribute("Value", String(value));
      cut.append(element);
    }
    entry.append(cut);
    material.append(entry);
  }
  return `<?xml version="1.0" encoding="utf-8"?>\n${new XMLSerializer().serializeToString(documentXml)}`;
}

function safeFilenamePart(value) {
  return value.normalize("NFKD")
    .replace(/[^A-Za-z0-9_.-]+/g, "-")
    .replace(/^[-.]+|[-.]+$/g, "")
    .slice(0, 120) || "material";
}

const form = document.querySelector('.template-generator[action="/docs/blank-palette-library/download"]');
if (form) {
  const input = form.querySelector("#template_material_name");
  const button = form.querySelector('button[type="submit"]');
  const status = document.createElement("p");
  status.className = "template-generator-status";
  status.setAttribute("role", "status");
  status.setAttribute("aria-live", "polite");
  form.append(status);

  form.addEventListener("submit", event => {
    event.preventDefault();
    const materialName = String(input?.value || "").trim();
    const invalid = !materialName || materialName.length > 160 || /[\u0000-\u001f\u007f]/.test(materialName);
    input.setCustomValidity(invalid ? "Material name must be between 1 and 160 characters and cannot contain control characters." : "");
    if (invalid) {
      input.reportValidity();
      status.textContent = "Correct the material name before generating the palette.";
      return;
    }

    button.disabled = true;
    try {
      const blob = new Blob([buildBlankPaletteXml(materialName)], {type: "application/xml;charset=utf-8"});
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${safeFilenamePart(materialName)}-blank-rasterizer-palette.clb`;
      link.hidden = true;
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      status.textContent = "Blank palette generated in this browser. No file was uploaded or stored.";
    } finally {
      button.disabled = false;
    }
  });
}
