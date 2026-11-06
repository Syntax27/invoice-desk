# Invoice desk

A local invoice intake and review tool for an operator working through a small batch. The visual language is an accounts ledger on warm paper, with navy ink and a restrained indigo accent. The product name is text. Use synthetic invoices explicitly labeled as samples.

## Design read

An invoice operations workspace for one operator, using a compact paper-ledger layout. ENERGY 1 / RHYTHM 2 / MOTION 1.

- A ruled queue keeps document names, dates, and amounts easy to compare. Use tabular numerals for invoice values and job references.
- Make the queue the focal point on the desk and the correction form the focal point during review. Put source text next to the fields on wide screens and beneath them on narrow screens.
- A warm neutral background separates the work surface from the document rows. Reserve indigo for primary actions and focus. Status words carry meaning independently of color.
- Use a system serif for the title to echo a ledger cover and a system sans serif for forms and records. Let spacing separate the main tasks.
- Keep motion to interaction feedback. Preserve keyboard focus, visible labels, and useful empty, working, and failure states.

## Anti-slop delivery gate

### Hard gate

| Rule | Result | Evidence |
| --- | --- | --- |
| R-02 | PASS | Checked authored interface copy for long dashes and generic calls to action. |
| R-03 | PASS | Chrome layouts fit at 320, 390, 768, and 1440 px. The review form reflows beneath its heading, and primary controls use 44 px minimum heights. |
| R-17 | PASS | Queue counts and attempts come from the database. |
| R-18 | PASS | The interface includes no testimonials. |
| R-23 | PASS | Text wordmark and task navigation use the app's name and real routes. The requested PDF fixtures are marked synthetic. |
| R-24 | PASS | Workspace, queue, filter, and error recovery links open their corresponding views. |
| R-25 | PASS | Checked text pairs measured at least 5.86:1 contrast. The primary action measured 8.85:1. |
| R-26 | PASS | Tested upload, sample loading, retry, approval, PDF download, CSV download, and queue controls. |
| R-27 | PASS | Verified empty, queued, processing, invalid upload, review error, failed, and ready states. |
| R-28 | PASS | Guidance sits next to the controls it explains. |
| R-32 | PASS | Tab reached the skip link, Enter moved to main content, and Enter on the focused approval button submitted the form. Inputs have visible focus styling. |
| R-33 | PASS | Templates, JavaScript, and CSS are maintained as source files. |
| R-34 | PASS | Checked the shipped light theme across the viewport widths above. |
| R-35 | PASS | Ran the app and completed the browser walkthrough below without JavaScript errors. |
| R-36 | PASS | Interface copy describes observed job state and supported operations. |
| R-37 | PASS | The design read and visual direction preceded interface work. |
| R-38 | PASS | Demo data is explicitly labeled as synthetic. Records appear after loading samples or uploading a file. |
| R-39 | PASS | Native links, buttons and inputs have accessible names, focus styles, and interaction feedback. Documents have named landmarks, language, and titles. |
| R-40 | PASS | Pages render with local CSS, deferred JavaScript, system fonts, and no layout media. |

Browser walkthrough

- Skip link moved focus to the main content. Workspace and back links returned to the queue. The mobile intake link focused the upload section.
- **Load sample invoices** queued three files. All five status filters and **All** showed the corresponding records. The empty filter link returned to all records. **Refresh queue** preserved the active filter.
- The file picker and drag-and-drop populated the upload input. **Upload PDF** opened an existing job for identical bytes and showed an error for a non-PDF.
- A filename opened the job. **Download original PDF** returned the original bytes. **Refresh status** reloaded the job, and polling reflected a transition out of processing. **Retry extraction** requeued a failed file.
- The four review inputs accepted edits. **Approve for export** showed a field error for an impossible date and approved the corrected date via keyboard. **Export CSV** downloaded all three ready records with the corrected date. A missing job offered a working route back to the queue.

### Purpose gate

| Rules | Result | Evidence |
| --- | --- | --- |
| R-01, R-07, R-10, R-12, R-13 | PASS | Paper tones and fine rules separate tasks and records. Surfaces stay flat for a ledger-like reading order. |
| R-04, R-08, R-22 | PASS | Text labels identify actions and destinations directly. |
| R-06 | PASS | Serif headings echo ledger covers. System sans serif and tabular figures support scanning. |
| R-09 | PASS | Compact status tags label real job states. |
| R-14 | PASS | The upload panel and invoice table have different structures suited to forms and records. |
| R-19 | PASS | Interaction feedback comes from color, borders, and focus. |

### Liveliness

| Check | Result | Evidence |
| --- | --- | --- |
| Dials and design read | PASS | The pre-build brief specifies 1 / 2 / 1. |
| Focal point and spacing | PASS | The ruled queue leads intake. The correction form leads review, with source text adjacent. |
| Accent and identity | PASS | Indigo marks primary actions and focus. Ledger rules, paper surfaces, and serif headings connect the views. |

### Craftsmanship and quality locks

| Rules | Result | Evidence |
| --- | --- | --- |
| C-1, C-3, R-05, R-20, R-30, R-31 | PASS | Each area supports intake, queue scanning, or source comparison. Layout and palette follow the written design read. |
| C-2, C-4 | PASS | The browser walkthrough covered the operational controls, mobile layouts, errors, and keyboard actions. |
| C-5, R-15, R-16 | PASS | Labels name the action and displayed totals come from job records. |
| R-11, R-21, R-29 | PASS | Small control radii, a light paper-and-ink palette, one action accent, and semantic state colors. |
