import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";

import { WorkspaceI18nProvider } from "./features/personal-workspace/i18n";
import { router } from "./router";
import "./styles.css";

const root = document.getElementById("root");

if (!root) {
  throw new Error("Root element not found");
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
      staleTime: 15_000,
    },
  },
});

createRoot(root).render(
  <QueryClientProvider client={queryClient}>
    <WorkspaceI18nProvider>
      <RouterProvider router={router} />
    </WorkspaceI18nProvider>
  </QueryClientProvider>,
);
