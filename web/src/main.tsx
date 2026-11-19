import { render } from "preact";
import "./fonts.css";
import "./styles.css";
import { initApi, setMapChooser } from "./api/http";
import { App } from "./app/App";
import { registerSW } from "./state/push";
import { chooseRepoMap } from "./state/repoMap";

setMapChooser(chooseRepoMap);

void initApi().then(() => render(<App />, document.getElementById("app")!));

void registerSW();
