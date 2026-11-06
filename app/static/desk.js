const dropTarget = document.querySelector("[data-file-drop]");

if (dropTarget) {
  const fileInput = dropTarget.querySelector("input[type=file]");
  if ("files" in fileInput) {
    dropTarget.querySelector("[data-drop-hint]").hidden = false;
    fileInput.addEventListener("change", () => fileInput.setCustomValidity(""));

    dropTarget.addEventListener("dragover", (event) => {
      if (!event.dataTransfer.types.includes("Files")) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = "copy";
      dropTarget.toggleAttribute("data-dragging", true);
    });

    dropTarget.addEventListener("dragleave", (event) => {
      if (!dropTarget.contains(event.relatedTarget)) {
        dropTarget.removeAttribute("data-dragging");
      }
    });

    dropTarget.addEventListener("drop", (event) => {
      event.preventDefault();
      dropTarget.removeAttribute("data-dragging");
      const { files } = event.dataTransfer;
      if (!files.length) return;
      if (files.length > 1) {
        fileInput.value = "";
        fileInput.setCustomValidity("Drop one PDF at a time.");
        fileInput.reportValidity();
        return;
      }

      fileInput.setCustomValidity("");
      fileInput.files = files;
      fileInput.focus();
    });
  }
}

const pendingJob = document.querySelector("[data-job-status]");

if (pendingJob) {
  const pollStatus = async () => {
    if (!document.hidden) {
      try {
        const response = await fetch(pendingJob.dataset.jobStatus, { cache: "no-store" });
        if (!response.ok) return;
        const { status } = await response.json();
        if (status !== pendingJob.dataset.currentStatus) {
          window.location.reload();
          return;
        }
      } catch {
        // A temporary connection failure can recover on the next check.
      }
    }
    window.setTimeout(pollStatus, 2500);
  };

  window.setTimeout(pollStatus, 2500);
}
