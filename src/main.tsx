import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider, createTheme } from "@mui/material/styles";
import { queryClient } from "./api";
import App from "./App";
import "./style.css";
const theme = createTheme({
  typography: { fontFamily: 'Inter, "Noto Sans TC", system-ui, sans-serif' },
  palette: { primary: { main: "#277c67" } },
  shape: { borderRadius: 12 },
});
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ThemeProvider theme={theme}>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </QueryClientProvider>
    </ThemeProvider>
  </React.StrictMode>,
);
