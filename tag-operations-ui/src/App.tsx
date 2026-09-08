import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowRight,
  Check,
  CircleDot,
  ExternalLink,
  FilePenLine,
  FileSpreadsheet,
  FolderOpen,
  Languages,
  LoaderCircle,
  Play,
  RefreshCw,
  Route,
  Settings2,
  Sparkles,
  Tags,
  TerminalSquare,
} from "lucide-react";

type Workflow = "dual_tagging" | "client_translation";
type Phase = "setup" | "running" | "mapping_ready" | "complete" | "error";

const workflowCopy = {
  dual_tagging: {
    eyebrow: "PAIR + SYNC",
    name: "Dual tagging",
    description: "Connect each client placeholder to its source asset, then keep both tag systems aligned.",
    icon: Tags,
  },
  client_translation: {
    eyebrow: "TRANSLATE IN PLACE",
    name: "Client translation",
    description: "Build a clean translation list from tagged entities and write approved client tags back in place.",
    icon: Languages,
  },
};

const steps = [
  ["Extract", "Read groups from DWG"],
  ["Index", "Build spatial registry"],
  ["Map", "Complete client workbook"],
  ["Write", "Update drawing + ATTSYNC"],
];

function scrambleTag(tag: string): string {
  if (!tag) return "";
  return tag
    .split("")
    .map((ch) => {
      if (ch >= "A" && ch <= "Z") {
        return String.fromCharCode(((ch.charCodeAt(0) - 65 + 1) % 26) + 65);
      }
      if (ch >= "a" && ch <= "z") {
        return String.fromCharCode(((ch.charCodeAt(0) - 97 + 1) % 26) + 97);
      }
      if (ch >= "0" && ch <= "9") {
        return String.fromCharCode(((ch.charCodeAt(0) - 48 + 1) % 10) + 48);
      }
      return ch;
    })
    .join("");
}

function App() {
  const [selectedWorkflows, setSelectedWorkflows] = useState<Workflow[]>(["dual_tagging"]);
  const [dwgPath, setDwgPath] = useState("");
  const [outputPath, setOutputPath] = useState("");
  const [mappingPath, setMappingPath] = useState("");
  const [downloadsDir, setDownloadsDir] = useState("C:\\Users\\PadXAutoman\\Downloads");
  const [phase, setPhase] = useState<Phase>("setup");
  const [logs, setLogs] = useState<string[]>([]);
  const [message, setMessage] = useState("");
  const [placeholderSummary, setPlaceholderSummary] = useState("CLIENT · XXX+");
  const [completedOutputs, setCompletedOutputs] = useState<Record<string, string>>({});

  const [showEditor, setShowEditor] = useState(false);
  const [gridRows, setGridRows] = useState<any[]>([]);
  const [savingGrid, setSavingGrid] = useState(false);
  const [gridSavedMessage, setGridSavedMessage] = useState("");

  const [showDumpModal, setShowDumpModal] = useState(false);
  const [dumpText, setDumpText] = useState("");
  const [dumpStatus, setDumpStatus] = useState("");

  const [highestStepReached, setHighestStepReached] = useState<number>(0);

  function toggleWorkflow(id: Workflow) {
    setSelectedWorkflows([id]);
  }

  function handleDwgPathChange(path: string) {
    setDwgPath(path);
    setPhase("setup");
    setHighestStepReached(0);
    setLogs([]);
    setMessage("");
    setCompletedOutputs({});
  }

  function applyDumpedTags() {
    if (!dumpText.trim()) {
      setDumpStatus("Please paste 2-column tag mapping data first.");
      return;
    }

    const lookup: Record<string, string> = {};
    const lines = dumpText.split(/\r?\n/);
    for (const line of lines) {
      if (!line.trim()) continue;
      const parts = line.split(/\t|,|\s{2,}/).map((p) => p.trim());
      if (parts.length >= 2 && parts[0] && parts[1]) {
        lookup[parts[0].toUpperCase()] = parts[1];
      }
    }

    let matchCount = 0;
    const nextGridRows = gridRows.map((row) => {
      const scovan = String(row["Scovan Tag"] || "").trim().toUpperCase();
      if (lookup[scovan]) {
        matchCount++;
        return { ...row, "Client Tag Mapping": lookup[scovan] };
      }
      return row;
    });

    setGridRows(nextGridRows);
    setDumpStatus(`Matched and updated ${matchCount} row(s) successfully!`);
    if (matchCount > 0) {
      setTimeout(() => {
        setShowDumpModal(false);
        setDumpText("");
        setDumpStatus("");
      }, 1200);
    }
  }

  const dwgFileInputRef = useRef<HTMLInputElement>(null);
  const outputFileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    fetch("/api/config")
      .then((response) => response.json())
      .then((config) => {
        const tokens = [...(config.placeholder_rules?.contains ?? []), "XXX+"];
        setPlaceholderSummary(tokens.join(" · "));
        if (config.downloads_dir) setDownloadsDir(config.downloads_dir);
      })
      .catch(() => undefined);
  }, []);

  const derivedMapping = useMemo(() => {
    if (mappingPath) return mappingPath;
    const hasSlash = /[\\/]/.test(dwgPath);
    const base = hasSlash ? dwgPath.replace(/[\\/][^\\/]+$/, "") : "";
    return base ? `${base}\\Client_Mapping_Sheet.xlsx` : "Client_Mapping_Sheet.xlsx";
  }, [dwgPath, mappingPath]);

  useEffect(() => {
    if (dwgPath.trim()) {
      const fileName = dwgPath.split(/[\\/]/).pop() || "";
      const isZip = /\.zip$/i.test(fileName);
      const ext = isZip ? ".zip" : ".dwg";
      const rawStem = fileName.replace(/\.(dwg|zip)$/i, "") || "drawing";
      const cleanStem = rawStem
        .replace(/_Updated$/i, "")
        .replace(/_(dualtagged|translated)$/i, "");
      const suffix = selectedWorkflows[0] === "client_translation" ? "_translated" : "_dualtagged";
      setOutputPath(`${cleanStem}${suffix}${ext}`);
    }
  }, [dwgPath, selectedWorkflows]);

  const defaultOutputName = useMemo(() => {
    const suffix = selectedWorkflows[0] === "client_translation" ? "_translated" : "_dualtagged";
    if (!dwgPath.trim()) return `${suffix}.dwg`;
    const fileName = dwgPath.split(/[\\/]/).pop() || "";
    const isZip = /\.zip$/i.test(fileName);
    const ext = isZip ? ".zip" : ".dwg";
    const rawStem = fileName.replace(/\.(dwg|zip)$/i, "") || "drawing";
    const cleanStem = rawStem
      .replace(/_Updated$/i, "")
      .replace(/_(dualtagged|translated)$/i, "");
    return `${cleanStem}${suffix}${ext}`;
  }, [dwgPath, selectedWorkflows]);

  const derivedOutput = useMemo(() => {
    const chosen = outputPath.trim() || defaultOutputName;
    if (/[\\/]/.test(chosen)) {
      return chosen;
    }
    return `${downloadsDir}\\${chosen}`;
  }, [outputPath, defaultOutputName, downloadsDir]);

  async function fetchMappingData(filePath: string) {
    try {
      setGridSavedMessage("");
      const response = await fetch(`/api/mapping?path=${encodeURIComponent(filePath)}`);
      const data = await response.json();
      if (response.ok && data.rows) {
        setGridRows(data.rows);
        setShowEditor(true);
      } else {
        alert(data.error || "Could not load mapping data.");
      }
    } catch {
      alert("Error fetching mapping data from service.");
    }
  }

  async function saveMappingData(filePath: string) {
    setSavingGrid(true);
    setGridSavedMessage("");
    try {
      const response = await fetch("/api/mapping", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: filePath, rows: gridRows }),
      });
      const data = await response.json();
      if (response.ok) {
        setGridSavedMessage(`Saved ${data.rows} mappings successfully! Click 'Validate & finish drawing' when ready.`);
      } else {
        alert(data.error || "Could not save mapping sheet.");
      }
    } catch {
      alert("Error saving mapping sheet to server.");
    } finally {
      setSavingGrid(false);
    }
  }

  async function openExcel(filePath: string) {
    try {
      const response = await fetch("/api/open-file", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: filePath }),
      });
      const data = await response.json();
      if (!response.ok) {
        fetchMappingData(filePath);
      }
    } catch {
      fetchMappingData(filePath);
    }
  }

  function browsePath(mode: "file" | "output") {
    if (mode === "file" && dwgFileInputRef.current) {
      dwgFileInputRef.current.click();
    } else if (mode === "output" && outputFileInputRef.current) {
      outputFileInputRef.current.click();
    }
  }

  async function run(action: "prepare" | "finalize") {
    if (action === "prepare") {
      setHighestStepReached(0);
    } else if (action === "finalize") {
      setHighestStepReached(3);
    }
    setPhase("running");
    setMessage("");
    setLogs([]);
    try {
      const response = await fetch(`/api/${action}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          workflow: selectedWorkflows.join(","),
          dwg_path: dwgPath,
          mapping_path: derivedMapping,
          output_path: outputPath || derivedOutput,
        }),
      });
      const { run_id, error } = await response.json();
      if (!response.ok) throw new Error(error || "Could not start the run.");
      poll(run_id, action);
    } catch (error) {
      setPhase("error");
      setMessage(error instanceof Error ? error.message : "Could not start the run.");
    }
  }

  function poll(runId: string, action: "prepare" | "finalize") {
    const timer = window.setInterval(async () => {
      try {
        const response = await fetch(`/api/runs/${runId}`);
        const run = await response.json();
        setLogs(run.logs ?? []);
        if (run.status === "complete") {
          window.clearInterval(timer);
          setPhase(action === "prepare" ? "mapping_ready" : "complete");
          if (run.result?.paths?.mapping) setMappingPath(run.result.paths.mapping);
          if (run.result?.outputs) {
            setCompletedOutputs(run.result.outputs);
          } else if (run.result?.paths?.output) {
            setCompletedOutputs({ [selectedWorkflows[0]]: run.result.paths.output });
          }
          setMessage(
            action === "prepare"
              ? `${run.result.mapping_rows} mappings are ready. Fill the workbook, save it, then finish the drawing.`
              : `Processing complete! Created output file(s).`,
          );
        }
        if (run.status === "error") {
          window.clearInterval(timer);
          const isUnmappedWarning =
            run.error &&
            (run.error.includes("Fill in all client mappings first") ||
              run.error.includes("blank row") ||
              run.error.includes("Worksheet named 'Mapping' not found"));
          if (isUnmappedWarning) {
            setPhase("mapping_ready");
            setHighestStepReached(2);
            setMessage("⚠️ Warning: Not all elements are mapped yet. Please complete all client mappings before finishing the drawing.");
          } else {
            setPhase("error");
            setMessage(run.error || "The workflow stopped.");
          }
        }
      } catch {
        window.clearInterval(timer);
        setPhase("error");
        setMessage("Lost connection to the local workflow service.");
      }
    }, 850);
  }

  useEffect(() => {
    let calculated = 0;
    if (phase === "complete") {
      calculated = 4;
    } else if (phase === "mapping_ready") {
      calculated = 2;
    } else if (phase === "running") {
      if (logs.some((l) => l.includes("04 ") || l.includes("05 ") || l.includes("06 ") || l.includes("Applying tags") || l.includes("ATTSYNC") || l.includes("Exporting"))) {
        calculated = 3;
      } else if (logs.some((l) => l.includes("03 ") || l.includes("Creating the client mapping"))) {
        calculated = 2;
      } else if (logs.some((l) => l.includes("02 ") || l.includes("Building the shared spatial registry"))) {
        calculated = 1;
      } else {
        calculated = 0;
      }
    }
    setHighestStepReached((prev) => Math.max(prev, calculated));
  }, [phase, logs]);

  const ready = Boolean(dwgPath.trim());
  const currentStep = useMemo(() => {
    if (phase === "complete") return 4;
    let calc = 0;
    if (phase === "mapping_ready") {
      calc = 2;
    } else if (phase === "running") {
      if (logs.some((l) => l.includes("04 ") || l.includes("05 ") || l.includes("06 ") || l.includes("Applying tags") || l.includes("ATTSYNC") || l.includes("Exporting"))) {
        calc = 3;
      } else if (logs.some((l) => l.includes("03 ") || l.includes("Creating the client mapping"))) {
        calc = 2;
      } else if (logs.some((l) => l.includes("02 ") || l.includes("Building the shared spatial registry"))) {
        calc = 1;
      } else {
        calc = 0;
      }
    }
    return Math.max(highestStepReached, calc);
  }, [phase, logs, highestStepReached]);

  return (
    <main className="app-shell">
      {/* Hidden file inputs */}
      <input
        type="file"
        ref={dwgFileInputRef}
        accept=".dwg,.zip"
        style={{ display: "none" }}
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) {
            const p = (file as any).path || file.name;
            setDwgPath(p);
          }
        }}
      />
      <input
        type="file"
        ref={outputFileInputRef}
        accept=".dwg,.zip"
        style={{ display: "none" }}
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) {
            const p = (file as any).path || file.name;
            setOutputPath(p);
          }
        }}
      />

      <section className="industrial-banner" id="top" style={{ marginTop: "12px", padding: "16px 24px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "20px" }}>
          <img
            src="/scovan_logo.png"
            alt="Scovan Logo"
            style={{ height: "46px", width: "auto", objectFit: "contain", display: "block" }}
          />
          <div style={{ width: "1px", height: "42px", background: "#3d4628" }} />
          <div className="banner-title">
            <h1 style={{ fontSize: "32px", fontWeight: 800, margin: 0, color: "#fff", letterSpacing: "-0.02em", lineHeight: 1.1 }}>PadXPRESS</h1>
            <div style={{ fontSize: "15px", fontWeight: 700, color: "#FF8200", letterSpacing: "1.5px", marginTop: "4px" }}>
              Dual Tagging and Translation
            </div>
          </div>
        </div>
        <div className="banner-meta">
          <div><small>CAD RUNTIME</small><strong>AutoCAD + ODA Direct</strong></div>
          <div><small>ENVIRONMENT</small><strong>Local Engine :: Port 8765</strong></div>
        </div>
      </section>

      <section className="workflow-picker" aria-label="Choose workflow">
        {(Object.keys(workflowCopy) as Workflow[]).map((id) => {
          const item = workflowCopy[id];
          const Icon = item.icon;
          const isSelected = selectedWorkflows[0] === id;
          return (
            <button
              key={id}
              type="button"
              className={`workflow-card ${isSelected ? "selected" : ""}`}
              onClick={() => toggleWorkflow(id)}
              style={{ position: "relative" }}
            >
              <span className="workflow-icon"><Icon size={24} /></span>
              <span className="workflow-copy">
                <small>{item.eyebrow}</small>
                <strong>{item.name}</strong>
                <span>{item.description}</span>
              </span>
              <span
                className="radio"
                style={{
                  background: isSelected ? "#3c2525" : "transparent",
                  border: isSelected ? "2px solid #3c2525" : "1px solid #525a37",
                  borderRadius: "50%",
                  width: "22px",
                  height: "22px",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  color: "#FF8200",
                }}
              >
                {isSelected && <CircleDot size={16} strokeWidth={3} />}
              </span>
            </button>
          );
        })}
      </section>

      <section className="workspace-grid">
        <div className="control-panel">
          <div className="panel-title">
            <div>
              <span>RUN SETUP</span>
              <h2>{workflowCopy[selectedWorkflows[0] || "dual_tagging"].name}</h2>
            </div>
          </div>

          <label className="field-label" htmlFor="dwg-path">INPUT <span>Required (.dwg or .zip)</span></label>
          <div className="path-field" style={{ cursor: "pointer" }} onClick={() => browsePath("file")}>
            <FilePenLine size={19} />
            <input
              id="dwg-path"
              value={dwgPath}
              onChange={(e) => setDwgPath(e.target.value)}
              onClick={(e) => e.stopPropagation()}
              placeholder="Select or enter drawing or zip path (.dwg, .zip)..."
            />
            <button
              type="button"
              className="browse-button"
              title="Click to select source DWG file"
              onClick={(e) => {
                e.stopPropagation();
                browsePath("file");
              }}
            >
              <FolderOpen size={18} />
            </button>
          </div>

          <label className="field-label" htmlFor="output-path">OUTPUT NAME <span>Saved to Downloads folder</span></label>
          <div className="path-field" style={{ cursor: "pointer" }} onClick={() => browsePath("output")}>
            <FilePenLine size={19} />
            <input
              id="output-path"
              value={outputPath}
              onChange={(e) => setOutputPath(e.target.value)}
              onClick={(e) => e.stopPropagation()}
              placeholder={defaultOutputName}
            />
            <button
              type="button"
              className="browse-button"
              title="Click to select output location"
              onClick={(e) => {
                e.stopPropagation();
                browsePath("output");
              }}
            >
              <FolderOpen size={18} />
            </button>
          </div>

          <div className="action-row">
            <button className="primary-button" disabled={!ready || phase === "running"} onClick={() => run("prepare")}>
              {phase === "running" ? <LoaderCircle className="spin" size={19} /> : <Play size={18} fill="currentColor" />}
              Prepare mapping
              <ArrowRight size={18} />
            </button>
            <p>Extracts groups, indexes entities, and creates the unified mapping workbook.</p>
          </div>

          {(phase === "mapping_ready" || phase === "complete") && (
            <div className="mapping-ready">
              <div
                className="mapping-header"
                style={{ cursor: "pointer" }}
                title="Click to edit mapping sheet in browser"
                onClick={() => fetchMappingData(derivedMapping)}
              >
                <FileSpreadsheet size={20} />
                <div>
                  <small>CLIENT MAPPING WORKBOOK</small>
                  <strong>{derivedMapping}</strong>
                </div>
                <Check size={19} />
              </div>
              <p>Open the web editor, fill client mapping cells for selected workflow(s), save, and finish drawing.</p>

              <div style={{ display: "flex", gap: "12px", marginTop: "14px", flexWrap: "wrap" }}>
                <button
                  className="primary-button"
                  style={{ minWidth: "auto", height: "44px", padding: "0 18px", background: "#3c2525", color: "#ffffff", border: "1px solid #525a37" }}
                  onClick={() => fetchMappingData(derivedMapping)}
                >
                  <FileSpreadsheet size={18} /> Open Online Mapping Editor
                </button>

                <button
                  className="secondary-button"
                  disabled={phase === "running"}
                  onClick={() => run("finalize")}
                >
                  <RefreshCw size={18} /> Validate & finish drawing
                </button>
              </div>

              {phase === "complete" && Object.keys(completedOutputs).length > 0 && (
                <div style={{ marginTop: "20px", paddingTop: "16px", borderTop: "1px dashed #3a4035" }}>
                  <div style={{ fontSize: "12px", fontWeight: 700, color: "#FF8200", letterSpacing: "1px", marginBottom: "10px" }}>
                    DOWNLOAD GENERATED OUTPUTS SEPARATELY
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
                    {Object.entries(completedOutputs).map(([wfKey, filePath]) => {
                      const fileName = filePath.split(/[\\/]/).pop() || filePath;
                      const label =
                        wfKey === "dual_tagging"
                          ? "Dual Tagged DWG Drawing"
                          : wfKey === "dual_tagging_pdf"
                          ? "Dual Tagged Vector PDF"
                          : wfKey === "client_translation"
                          ? "Client Translated DWG Drawing"
                          : wfKey === "client_translation_pdf"
                          ? "Client Translated Vector PDF"
                          : wfKey.endsWith("_pdf")
                          ? "Vector PDF Document"
                          : "Updated CAD Drawing";
                      return (
                        <div
                          key={wfKey}
                          style={{
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "space-between",
                            background: "#252d1d",
                            border: "1px solid #3d4628",
                            borderRadius: "8px",
                            padding: "10px 14px",
                          }}
                        >
                          <div>
                            <small style={{ color: "#b0bc9c", fontSize: "11px", fontWeight: 600, display: "block" }}>
                              {label.toUpperCase()}
                            </small>
                            <strong style={{ color: "#fff", fontSize: "13px" }}>{fileName}</strong>
                          </div>
                          <div style={{ display: "flex", gap: "8px" }}>
                            <a
                              href={`/api/download?path=${encodeURIComponent(filePath)}`}
                              download={fileName}
                              style={{
                                display: "inline-flex",
                                alignItems: "center",
                                gap: "6px",
                                padding: "6px 14px",
                                borderRadius: "6px",
                                background: "#3c2525",
                                color: "#ffffff",
                                border: "1px solid #525a37",
                                fontWeight: 700,
                                fontSize: "12px",
                                textDecoration: "none",
                              }}
                            >
                              ⬇️ Download
                            </a>
                            <button
                              onClick={() => openExcel(filePath)}
                              style={{
                                padding: "6px 12px",
                                borderRadius: "6px",
                                background: "#364028",
                                border: "1px solid #525a37",
                                color: "#f2f3ef",
                                fontSize: "12px",
                                cursor: "pointer",
                              }}
                            >
                              Open File
                            </button>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          )}

          {message && <div className={`notice ${phase}`}>{phase === "error" ? "RUN STOPPED" : "STATUS"}<span>{message}</span></div>}
        </div>

        <aside className="run-panel">
          <div className="panel-title compact">
            <div><span>PIPELINE</span><h2>Run progress</h2></div>
            <span className={`run-state ${phase}`}>{phase === "running" ? "RUNNING" : phase.replace("_", " ")}</span>
          </div>
          <div className="step-rail">
            {steps.map(([title, detail], index) => {
              const complete = index < currentStep || phase === "complete";
              const active = index === currentStep && phase === "running";
              return (
                <div className={`pipeline-step ${complete ? "done" : ""} ${active ? "active" : ""}`} key={title}>
                  <span className="step-node">{complete ? <Check size={14} /> : String(index + 1).padStart(2, "0")}</span>
                  <div><strong>{title}</strong><span>{detail}</span></div>
                </div>
              );
            })}
          </div>
        </aside>
      </section>

      {/* WEB SPREADSHEET EDITOR MODAL */}
      {showEditor && (
        <div style={{
          position: "fixed", top: 0, left: 0, right: 0, bottom: 0,
          backgroundColor: "rgba(0, 0, 0, 0.8)", zIndex: 1000,
          display: "flex", justifyContent: "center", alignItems: "center", padding: "20px"
        }}>
          <div style={{
            backgroundColor: "#252d1d", border: "1px solid #525a37", borderRadius: "12px",
            width: "100%", maxWidth: "920px", maxHeight: "88vh", display: "flex", flexDirection: "column",
            boxShadow: "0 20px 50px rgba(0,0,0,0.8)", color: "#ecefe9", padding: "24px"
          }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
              <div>
                <span style={{ fontSize: "11px", color: "#FF8200", fontWeight: 700, letterSpacing: "1px" }}>WEB SPREADSHEET EDITOR</span>
                <h2 style={{ margin: "4px 0 0 0", fontSize: "22px", fontWeight: 700 }}>Client Tag Mapping Sheet</h2>
              </div>
              <button
                onClick={() => setShowEditor(false)}
                style={{ background: "transparent", border: "none", color: "#8f959e", cursor: "pointer", fontSize: "22px" }}
              >✕</button>
            </div>

            <div style={{ display: "flex", gap: "10px", marginBottom: "16px", flexWrap: "wrap" }}>
              <button
                onClick={() => {
                  setGridRows((prev) =>
                    prev.map((r) => ({
                      ...r,
                      "Client Tag Mapping": r["Client Tag Mapping"] || r["Scovan Tag"] || "",
                    }))
                  );
                }}
                style={{ padding: "8px 14px", fontSize: "12px", fontWeight: 600, borderRadius: "6px", border: "1px solid #525a37", background: "#364028", color: "#f2f3ef", cursor: "pointer" }}
              >
                ⚡ Auto-fill from Scovan Tags
              </button>
              <button
                onClick={() => {
                  setGridRows((prev) =>
                    prev.map((r) => ({
                      ...r,
                      "Client Tag Mapping": scrambleTag(r["Scovan Tag"] || r["Client Tag Mapping"] || ""),
                    }))
                  );
                }}
                style={{ padding: "8px 14px", fontSize: "12px", fontWeight: 600, borderRadius: "6px", border: "1px solid #525a37", background: "#364028", color: "#f2f3ef", cursor: "pointer" }}
                title="Shift every letter forward by 1 (A->B, Z->A) and every number by 1 (0->1, 9->0)"
              >
                🔀 Scramble (+1 Shift)
              </button>
              <button
                onClick={() => {
                  setDumpStatus("");
                  setDumpText("");
                  setShowDumpModal(true);
                }}
                style={{ padding: "8px 14px", fontSize: "12px", fontWeight: 600, borderRadius: "6px", border: "1px solid #525a37", background: "#364028", color: "#f2f3ef", cursor: "pointer" }}
                title="Paste 2-column Excel mapping data (Col 1 = Scovan Tag, Col 2 = Client Tag)"
              >
                📋 Dump Tags (Paste Mapping)
              </button>
              <button
                onClick={() => {
                  setGridRows((prev) =>
                    prev.map((r) => ({ ...r, "Client Tag Mapping": "" }))
                  );
                }}
                style={{ padding: "8px 14px", fontSize: "12px", fontWeight: 600, borderRadius: "6px", border: "1px solid #454f33", background: "#282f1f", color: "#adb79f", cursor: "pointer" }}
              >
                🗑️ Clear All Mappings
              </button>
            </div>

            <div style={{ flex: 1, overflowY: "auto", border: "1px solid #525a37", borderRadius: "8px", background: "#121415" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", textAlign: "left", fontSize: "13px" }}>
                <thead>
                  <tr style={{ background: "#2a321f", borderBottom: "2px solid #525a37", color: "#c8d4b8", position: "sticky", top: 0, zIndex: 10 }}>
                    <th style={{ padding: "12px 16px", width: "60px" }}>Row</th>
                    <th style={{ padding: "12px 16px" }}>Scovan Tag / Source</th>
                    <th style={{ padding: "12px 16px" }}>Client Tag Mapping (Editable)</th>
                  </tr>
                </thead>
                <tbody>
                  {gridRows.map((row, idx) => (
                    <tr key={idx} style={{ borderBottom: "1px solid #222529" }}>
                      <td style={{ padding: "10px 16px", color: "#6e766a" }}>{idx + 1}</td>
                      <td style={{ padding: "10px 16px", fontWeight: 600, color: "#dcdfd8" }}>{row["Scovan Tag"]}</td>
                      <td style={{ padding: "10px 16px" }}>
                        <input
                          type="text"
                          value={row["Client Tag Mapping"] ?? ""}
                          onChange={(e) => {
                            const val = e.target.value;
                            setGridRows((prev) => {
                              const updated = [...prev];
                              updated[idx] = { ...updated[idx], "Client Tag Mapping": val };
                              return updated;
                            });
                          }}
                          placeholder="Type client tag mapping here..."
                          style={{
                            width: "100%", padding: "8px 12px", background: "#151719", border: "1px solid #363b42",
                            borderRadius: "6px", color: "#FF8200", fontSize: "14px", fontWeight: 600, outline: "none"
                          }}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {gridSavedMessage && (
              <div style={{ marginTop: "12px", color: "#FF8200", fontSize: "13px", fontWeight: 600 }}>
                ✓ {gridSavedMessage}
              </div>
            )}

            <div style={{ display: "flex", justifyContent: "flex-end", gap: "12px", marginTop: "18px" }}>
              <button
                onClick={() => setShowEditor(false)}
                style={{ padding: "10px 18px", borderRadius: "6px", background: "transparent", border: "1px solid #383d44", color: "#ccc", cursor: "pointer" }}
              >
                Close
              </button>
              <button
                onClick={() => saveMappingData(derivedMapping)}
                disabled={savingGrid}
                style={{
                  padding: "10px 24px", borderRadius: "6px", background: "#3c2525", border: "1px solid #525a37", color: "#ffffff",
                  fontWeight: 700, cursor: "pointer", display: "flex", alignItems: "center", gap: "8px"
                }}
              >
                💾 {savingGrid ? "Saving..." : "Save Mapping Sheet"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* DUMP TAGS PASTE MODAL */}
      {showDumpModal && (
        <div style={{
          position: "fixed", top: 0, left: 0, right: 0, bottom: 0,
          backgroundColor: "rgba(0, 0, 0, 0.85)", zIndex: 1100,
          display: "flex", justifyContent: "center", alignItems: "center", padding: "20px"
        }}>
          <div style={{
            backgroundColor: "#252d1d", border: "1px solid #525a37", borderRadius: "12px",
            width: "100%", maxWidth: "680px", display: "flex", flexDirection: "column",
            boxShadow: "0 20px 50px rgba(0,0,0,0.9)", color: "#ecefe9", padding: "24px"
          }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
              <div>
                <span style={{ fontSize: "11px", color: "#FF8200", fontWeight: 700, letterSpacing: "1px" }}>BULK PASTE</span>
                <h2 style={{ margin: "4px 0 0 0", fontSize: "20px", fontWeight: 700 }}>Dump Tag Mappings</h2>
              </div>
              <button
                onClick={() => setShowDumpModal(false)}
                style={{ background: "transparent", border: "none", color: "#8f959e", cursor: "pointer", fontSize: "22px" }}
              >✕</button>
            </div>

            <p style={{ fontSize: "13px", color: "#a8b0a2", margin: "0 0 12px 0" }}>
              Paste 2-column mapping data from Excel or text (Col 1 = Scovan Tag, Col 2 = Client Tag). Any exact matching Scovan tags will automatically be filled.
            </p>

            <textarea
              value={dumpText}
              onChange={(e) => setDumpText(e.target.value)}
              placeholder={`Paste 2-column data here...\nExample:\n33GA-C4-C5\tCLIENT-TAG-01\n114GA-C1-C5#\tCLIENT-TAG-02`}
              rows={10}
              style={{
                width: "100%", padding: "12px", background: "#161b11", border: "1px solid #525a37",
                borderRadius: "6px", color: "#FF8200", fontFamily: "monospace", fontSize: "13px", outline: "none"
              }}
            />

            {dumpStatus && (
              <div style={{ marginTop: "12px", color: "#FF8200", fontSize: "13px", fontWeight: 600 }}>
                {dumpStatus}
              </div>
            )}

            <div style={{ display: "flex", justifyContent: "flex-end", gap: "12px", marginTop: "16px" }}>
              <button
                onClick={() => setShowDumpModal(false)}
                style={{ padding: "8px 16px", borderRadius: "6px", background: "transparent", border: "1px solid #383d44", color: "#ccc", cursor: "pointer" }}
              >
                Cancel
              </button>
              <button
                onClick={applyDumpedTags}
                style={{
                  padding: "8px 20px", borderRadius: "6px", background: "#3c2525", border: "1px solid #525a37", color: "#ffffff",
                  fontWeight: 700, cursor: "pointer"
                }}
              >
                Match & Apply Mappings
              </button>
            </div>
          </div>
        </div>
      )}

      <footer><span>PADXPRESS · TAG OPERATIONS</span></footer>
    </main>
  );
}

export default App;
