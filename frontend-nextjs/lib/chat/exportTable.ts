import * as XLSX from "xlsx";

// Export a rendered markdown <table> to Excel / CSV. Reads the DOM table
// directly (headers from thead, rows from tbody) so it exports exactly what
// the user sees.

function extractTableData(table: HTMLTableElement): string[][] {
  const data: string[][] = [];

  const thead = table.querySelector("thead");
  const headerRow = thead?.querySelector("tr");
  if (headerRow) {
    const headers: string[] = [];
    headerRow.querySelectorAll("th").forEach((th) => headers.push(th.textContent?.trim() || ""));
    if (headers.length) data.push(headers);
  }

  const tbody = table.querySelector("tbody");
  if (tbody) {
    tbody.querySelectorAll("tr").forEach((row) => {
      const rowData: string[] = [];
      row.querySelectorAll("td").forEach((td) => rowData.push(td.textContent?.trim() || ""));
      if (rowData.length) data.push(rowData);
    });
  }

  // Fallback: no thead/tbody — read every row's cells.
  if (data.length === 0) {
    table.querySelectorAll("tr").forEach((row) => {
      const rowData: string[] = [];
      row.querySelectorAll("th, td").forEach((cell) => rowData.push(cell.textContent?.trim() || ""));
      if (rowData.length) data.push(rowData);
    });
  }

  return data;
}

export function sanitizeFileName(name: string): string {
  return (name || "table-export").replace(/[^\w.-]+/g, "-").replace(/-+/g, "-").replace(/^-|-$/g, "") || "table-export";
}

export function exportTableToExcel(table: HTMLTableElement, fileName = "table-export"): void {
  const rows = extractTableData(table);
  if (!rows.length) throw new Error("No data found in table");

  const workbook = XLSX.utils.book_new();
  const worksheet = XLSX.utils.aoa_to_sheet(rows);

  // Auto-size columns to their widest cell (capped).
  const widths: number[] = [];
  rows.forEach((row) => row.forEach((cell, i) => {
    widths[i] = Math.max(widths[i] || 10, cell.length);
  }));
  worksheet["!cols"] = widths.map((w) => ({ wch: Math.min(w + 2, 50) }));

  XLSX.utils.book_append_sheet(workbook, worksheet, "Sheet1");
  XLSX.writeFile(workbook, `${sanitizeFileName(fileName)}.xlsx`);
}

export function exportTableToCSV(table: HTMLTableElement, fileName = "table-export"): void {
  const rows = extractTableData(table);
  if (!rows.length) throw new Error("No data found in table");

  const csv = rows
    .map((row) =>
      row
        .map((cell) => {
          const needsQuote = /[",\n]/.test(cell);
          const escaped = cell.replace(/"/g, '""');
          return needsQuote ? `"${escaped}"` : escaped;
        })
        .join(",")
    )
    .join("\n");

  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${sanitizeFileName(fileName)}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
