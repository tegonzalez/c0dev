pandoc -t markdown_strict --extract-media="./attachments/${1%.*}" "$1" -o "${1%.*}.md"

