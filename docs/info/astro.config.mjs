import { defineConfig } from "astro/config";
import mdx from "@astrojs/mdx";
import starlight from "@astrojs/starlight";
import logo from "./src/assets/logo.png";

const isGitHubActions = process.env.GITHUB_ACTIONS === "true";
const repoName = process.env.GITHUB_REPOSITORY?.split("/")[1];
const pagesUrl = process.env.GITHUB_PAGES_URL;
const normalizeBase = (value) => {
  if (!value || value === "/") return "/";
  const withLeadingSlash = value.startsWith("/") ? value : `/${value}`;
  return withLeadingSlash.endsWith("/")
    ? withLeadingSlash
    : `${withLeadingSlash}/`;
};
const pagesBasePath = (() => {
  if (!pagesUrl) return "";
  try {
    const pathname = new URL(pagesUrl).pathname;
    return normalizeBase(pathname);
  } catch {
    return "";
  }
})();

export default defineConfig({
  site: pagesUrl ?? "https://plurality-run.github.io",
  base: isGitHubActions
    ? pagesBasePath || (repoName ? normalizeBase(`/${repoName}`) : "/")
    : "/",
  integrations: [
    starlight({
      title: "Synchronic Web",
      description: "Documentation for usage, operation, development, and research.",
      favicon: "/images/favicon.ico",
      head: [],
      logo: {
        src: logo,
      },
      customCss: ["./src/styles/custom.css"],
      disable404Route: true,
      sidebar: [
        {
          label: "Documentation",
          items: [
            { slug: "index", label: "Overview" },
            { slug: "usage", label: "Usage" },
            { slug: "operation", label: "Operation" },
            { slug: "development", label: "Development" },
            { slug: "tools", label: "Tools" },
            { slug: "research", label: "Research" },
            { slug: "glossary", label: "Glossary" },
          ],
        },
      ],
    }),
    mdx(),
  ],
});
