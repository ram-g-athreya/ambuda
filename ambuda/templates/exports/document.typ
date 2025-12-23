#set page(
  paper: "a4",
  margin: 2cm,
)

#set text(
  size: 12pt,
  lang: "sa",
)

#set par(
  leading: 0.65em,
  spacing: 1.5em,
)

#let sa = text.with(font: "Noto Serif Devanagari", lang: "sa")

#align(center)[
  #sa[#text(size: 20pt)[*{title}*]]
]

#align(center)[
  #text(size: 9pt, fill: rgb("#666666"))[Exported from ambuda.org on {timestamp}]
]

#v(1em)

{content}
