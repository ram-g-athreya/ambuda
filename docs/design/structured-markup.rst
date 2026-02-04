Structured markup
=================

This document describes how we apply structured markup to projects and texts.

Background
----------

It is useful for us to know whether some words in a text represent a paragraph, a verse, a heading,
or something else. This knowledge helps us present content beautifully to the reader and create
table of contents pages and other artifacts that rely on a structured understanding of the text.
Likewise, it is useful to know whether some text in a text is a correction, an error, or something
else. This knowledge makes it clear where and how a digital text diverges from the source text it
comes from.

These and other considerations mean that we want to have a consistent markup for the texts we
publish on Ambuda.


Text markup
-----------

In the world of diginal humanities, the consensus markup standard for texts is TEI XML, which is
ordinary XML that follows the schema defined by the TEI Consortium. This is the markup we use for
all of Ambuda's texts.

TEI is an enormously complicated spec, and we use only a fraction of it in our work. For a formal
definition of the TEI subset we use and accept, see `TEI_XML_VALIDATION_SPEC` in
`ambuda/utils/xml_validation.py`.


Proofing markup
---------------

*Proofing* is our way of converting a scanned book into one or more published texts. We think of
our proofed projects as *semi-structured*, meaning that they have more structure than plain text
or the raw image but less structure than a TEI text. When a text is published from our proofing
projects, our backend code converts this semi-structured data into a fully conformant TEI document.

XML is a strong fit for marking up arbitrary text, and we had no desire to move away from it for
annotating proofed text. But the semi-structured nature of proofed text led us to consider if using
TEI markup was the best choice. After some consideration, we decided to use our own XML schema and
convert to TEI markup upon publishing the text.

Our proofing XML overlaps with TEI XML in many places, but it aims for different design goals:

- *Readability.* -- TEI XML uses tags like `<sic>`, `<corr>`, and `<lg>` which are cryptic to the
  uniniated. For those rare cases where a user needs to edit raw XML, we found it better to use
  obvious tags like `<error>`, `<fix>`, and `<verse>` instead.

- *Simplicity*. TEI XML uses complex nesting for features like dialog, where an `<sp>` element
  wraps the speaker, stage directions, and any other content associated with the speaker's
  performance. This is a complicated structure to maintain in a visual editor, especially for users
  who don't fully understand the underlying data model.

For a formal definition, see `PROOFING_XML_VALIDATION_SPEC` in `ambuda/utils/xml_validation.py`.
