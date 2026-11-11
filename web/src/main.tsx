import { render } from "preact";
import { signal } from "@preact/signals";
import "./fonts.css";
import { connectEvents } from "./api/sse";

const connected = signal(false);
const version = signal("");

connectEvents({
  onStatus: (ok) => (connected.value = ok),
  onHello: (h) => (version.value = h.version),
  onEvent: () => {},
});

function App() {
  return (
    <main style={{ fontFamily: "var(--font-ui)", padding: "2rem" }}>
      <h1 style={{ fontFamily: "var(--font-display)" }}>setu</h1>
      <p style={{ fontFamily: "var(--font-mono)" }}>
        {connected.value ? `connected ${version.value}` : "connecting"}
      </p>
    </main>
  );
}

render(<App />, document.getElementById("app")!);
