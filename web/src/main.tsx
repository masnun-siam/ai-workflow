import { render } from "preact";
import "./fonts.css";
import "./styles.css";
import { initApi } from "./api/http";
import { App } from "./app/App";

void initApi().then(() => render(<App />, document.getElementById("app")!));
