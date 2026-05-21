/**
 * Values for HTML ``<input type="file" accept="...">``.
 *
 * Include both extensions and MIME types so Linux/macOS/Windows file pickers
 * (the native "Open File" dialog with search) reliably show JSON-LD fixtures.
 */

/** Ontology / RDF / graph import (upload import tab, recall overlay, etc.). */
export const ONTOLOGY_IMPORT_FILE_ACCEPT =
  ".jsonld,.json-ld,.json,.ttl,.turtle,.owl,.rdf,.n3,.nt,.xml,.skos," +
  "application/ld+json,application/json,text/turtle,application/rdf+xml";

/** Document ingest (PDF, Office, Markdown) — not ontology graph formats. */
export const DOCUMENT_UPLOAD_FILE_ACCEPT =
  ".pdf,.docx,.pptx,.md,.markdown,application/pdf,text/markdown";

/** Unified upload page: documents + ontology files (type chosen by extension). */
export const UNIFIED_UPLOAD_FILE_ACCEPT =
  `${DOCUMENT_UPLOAD_FILE_ACCEPT},${ONTOLOGY_IMPORT_FILE_ACCEPT}`;

export type UploadFileKind = "ontology" | "document";

export function getUploadFileKind(filename: string): UploadFileKind {
  return isOntologyImportFilename(filename) ? "ontology" : "document";
}

export function isOntologyImportFilename(filename: string): boolean {
  const lower = filename.toLowerCase();
  return (
    lower.endsWith(".jsonld") ||
    lower.endsWith(".json-ld") ||
    lower.endsWith(".json") ||
    lower.endsWith(".ttl") ||
    lower.endsWith(".turtle") ||
    lower.endsWith(".owl") ||
    lower.endsWith(".rdf") ||
    lower.endsWith(".n3") ||
    lower.endsWith(".nt") ||
    lower.endsWith(".xml") ||
    lower.endsWith(".skos")
  );
}
