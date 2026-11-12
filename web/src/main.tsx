import { render } from "preact";
import "./fonts.css";
import "./styles.css";
import { initApi } from "./api/http";
import { App } from "./app/App";
import { registerSW } from "./state/push";

void initApi().then(() => render(<App />, document.getElementById("app")!));

void registerSW();
