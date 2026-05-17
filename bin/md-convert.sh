#!/bin/sh

set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

# User-tunable base folders.
# - Attachments are always created relative to the current working directory.
# - Templates are stored relative to the script location by default.
: "${MD_CONVERT_ATTACHMENTS_DIR:=attachments}"
: "${MD_CONVERT_TEMPLATES_DIR:=$script_dir/../rules/assets/templates}"

# Source-of-truth templates to copy from (missing files only).
: "${MD_CONVERT_TEMPLATE_SRC:=$script_dir/../rules/assets/templates}"

usage() {
  templates_note="(none found)"
  if [ -d "$MD_CONVERT_TEMPLATES_DIR" ]; then
    for f in "$MD_CONVERT_TEMPLATES_DIR"/*.docx; do
      [ -f "$f" ] || continue
      templates_note=""
      break
    done
  fi

  cat <<'USAGE' >&2
Usage:
  md-convert.sh [-f] [-o OUTPUT] <file> [docx|pdf] [template]

Behavior (inferred from <file> extension):
  - If <file> is Markdown (.md):
      You must provide the destination as the next argument: docx|pdf
      Default OUTPUT (no -o): same stem, extension replaced (e.g. a.md -> a.docx)
      Optional [template] applies only to docx and may be a path/filename.docx or a template name.
  - If <file> is anything else (e.g. .docx, .pdf, .rtf):
      Destination is assumed to be Markdown
      Do not provide docx|pdf or [template]
      Default OUTPUT (no -o): same stem with .md (e.g. a.docx -> a.md)

Output rules:
  - If OUTPUT exists, fail unless -f is provided.

Templates:
USAGE

  if [ -n "$templates_note" ]; then
    echo "  $templates_note" >&2
  else
    # List templates as names (no extension) for use as [template].
    for f in "$MD_CONVERT_TEMPLATES_DIR"/*.docx; do
      [ -f "$f" ] || continue
      b=$(basename -- "$f")
      echo "  - ${b%.docx}" >&2
    done
  fi

  cat <<'USAGE' >&2

Examples:
  ./md-convert.sh aoi.md docx
  ./md-convert.sh aoi.md docx pagenum-template
  ./md-convert.sh -o /tmp/aoi.docx aoi.md docx ./templates/pagenum-template.docx
  ./md-convert.sh contract.docx
  ./md-convert.sh scanned.pdf
USAGE
  exit 2
}

force=0
out=""

while getopts "fo:h" opt; do
  case "$opt" in
    f) force=1 ;;
    o) out="$OPTARG" ;;
    h) usage ;;
    *) usage ;;
  esac
done
shift $((OPTIND - 1))

[ "$#" -ge 1 ] || usage

in="$1"
shift

if [ ! -f "$in" ]; then
  echo "Input file not found: $in" >&2
  exit 2
fi

if ! command -v pandoc >/dev/null 2>&1; then
  echo "pandoc not found in PATH" >&2
  exit 127
fi

lower_ext() {
  # prints lowercased file extension (no dot), or empty string
  b=$(basename -- "$1")
  case "$b" in
    *.*) printf '%s' "${b##*.}" | tr '[:upper:]' '[:lower:]' ;;
    *) printf '%s' "" ;;
  esac
}

stem_path() {
  # prints input path without final extension (preserves directory)
  case "$1" in
    *.*) printf '%s' "${1%.*}" ;;
    *) printf '%s' "$1" ;;
  esac
}

default_out_for() {
  in_path="$1"
  dest_ext="$2"
  printf '%s.%s' "$(stem_path "$in_path")" "$dest_ext"
}

ensure_output_ok() {
  out_path="$1"
  if [ -e "$out_path" ] && [ "$force" -ne 1 ]; then
    echo "Refusing to overwrite existing output (use -f): $out_path" >&2
    exit 3
  fi
  out_dir=$(dirname -- "$out_path")
  if [ ! -d "$out_dir" ]; then
    echo "Output directory not found: $out_dir" >&2
    exit 2
  fi
}

copy_templates() {
  src="$MD_CONVERT_TEMPLATE_SRC"
  dst="$MD_CONVERT_TEMPLATES_DIR"

  if [ ! -d "$src" ]; then
    echo "Template source dir not found: $src" >&2
    exit 2
  fi

  mkdir -p "$dst"
  for f in "$src"/*; do
    base=$(basename -- "$f")
    [ -e "$dst/$base" ] || cp -pR "$f" "$dst/$base"
  done
}

pick_reference_docx() {
  tmpl="$MD_CONVERT_TEMPLATES_DIR"
  if [ -f "$tmpl/pagenum-template.docx" ]; then
    printf '%s' "$tmpl/pagenum-template.docx"
    return 0
  fi
  if [ -f "$tmpl/investor-flipper-template.docx" ]; then
    printf '%s' "$tmpl/investor-flipper-template.docx"
    return 0
  fi
  # fallback: first docx in template/
  for f in "$tmpl"/*.docx; do
    [ -f "$f" ] || continue
    printf '%s' "$f"
    return 0
  done
  return 1
}

resolve_template() {
  ref="$1"
  [ -n "$ref" ] || return 0

  if [ -f "$ref" ]; then
    printf '%s' "$ref"
    return 0
  fi
  if [ -f "$MD_CONVERT_TEMPLATES_DIR/$ref" ]; then
    printf '%s' "$MD_CONVERT_TEMPLATES_DIR/$ref"
    return 0
  fi
  if [ -f "$MD_CONVERT_TEMPLATES_DIR/$ref.docx" ]; then
    printf '%s' "$MD_CONVERT_TEMPLATES_DIR/$ref.docx"
    return 0
  fi
  return 1
}

md_to_docx() {
  in_md="$1"
  out_docx="$2"
  tmpl_arg="${3:-}"
  copy_templates
  ref="$(resolve_template "$tmpl_arg" 2>/dev/null || true)"
  if [ -z "${ref:-}" ]; then
    ref=$(pick_reference_docx || true)
  fi
  if [ -z "${ref:-}" ] || [ ! -f "$ref" ]; then
    echo "No reference .docx found under $MD_CONVERT_TEMPLATES_DIR/" >&2
    exit 2
  fi
  pandoc "$in_md" \
    --from markdown+smart+raw_html+hard_line_breaks \
    --to docx \
    --standalone \
    --reference-doc="$ref" \
    -o "$out_docx"
}

md_to_pdf() {
  in_md="$1"
  out_pdf="$2"
  # NOTE: PDF generation depends on an installed PDF engine (e.g., LaTeX).
  pandoc "$in_md" \
    --from markdown+smart+raw_html+hard_line_breaks \
    --to pdf \
    --standalone \
    -o "$out_pdf"
}

docx_to_md() {
  in_docx="$1"
  out_md="$2"
  stem=$(basename -- "$(stem_path "$in_docx")")
  media_dir="$MD_CONVERT_ATTACHMENTS_DIR/$stem"
  mkdir -p "$media_dir"
  pandoc -s "$in_docx" \
    --wrap=none \
    --extract-media="$media_dir" \
    --to gfm+hard_line_breaks \
    -o "$out_md"
}

pdf_to_md() {
  in_pdf="$1"
  out_md="$2"
  if ! command -v pdftotext >/dev/null 2>&1; then
    echo "pdftotext not found in PATH; PDF->MD is a placeholder until poppler is installed." >&2
    exit 127
  fi
  # Placeholder implementation; refine when pdftotext is available.
  pdftotext "$in_pdf" - > "$out_md"
}

rtf_to_md() {
  in_rtf="$1"
  out_md="$2"
  pandoc -s "$in_rtf" --wrap=none --to gfm+hard_line_breaks -o "$out_md"
}

ext=$(lower_ext "$in")

case "$ext" in
  md)
    [ "$#" -ge 1 ] || usage
    dest="$1"
    shift
    case "$dest" in
      docx|pdf) ;;
      *) usage ;;
    esac
    tmpl_arg=""
    if [ "$dest" = "docx" ]; then
      if [ "$#" -gt 1 ]; then
        usage
      fi
      tmpl_arg="${1:-}"
    else
      [ "$#" -eq 0 ] || usage
    fi
    if [ -z "$out" ]; then
      out=$(default_out_for "$in" "$dest")
    fi
    ensure_output_ok "$out"
    case "$dest" in
      docx) md_to_docx "$in" "$out" "$tmpl_arg" ;;
      pdf)  md_to_pdf "$in" "$out" ;;
    esac
    ;;
  *)
    [ "$#" -eq 0 ] || usage
    if [ -z "$out" ]; then
      out=$(default_out_for "$in" "md")
    fi
    ensure_output_ok "$out"
    case "$ext" in
      docx) docx_to_md "$in" "$out" ;;
      pdf)  pdf_to_md "$in" "$out" ;;
      rtf)  rtf_to_md "$in" "$out" ;;
      *)
        pandoc -s "$in" --wrap=none --to gfm+hard_line_breaks -o "$out"
        ;;
    esac
    ;;
esac
