"use strict";

const basisInfosButton = document.querySelector('.basis-infos__button');
const basisInfosCollapsible = document.querySelector('.basis-infos__collapsible');
basisInfosButton.addEventListener('click', () => {
    if(basisInfosButton.textContent === "Basisinformationen anzeigen") {
        basisInfosButton.textContent = "Basisinformationen verbergen";
        basisInfosCollapsible.style.maxHeight = `${basisInfosCollapsible.scrollHeight}px`;
        basisInfosCollapsible.style.border = "1px #DFDFDF solid";
    }
    else {
        basisInfosButton.textContent = 'Basisinformationen anzeigen';
        basisInfosCollapsible.style.maxHeight = 0;
        // without the timeout, the collapse animation will cause the border to remain visible despite being set to transparent
        setTimeout(() => {
            basisInfosCollapsible.style.border = "1px transparent solid";
        }, 50);
    }
});

document.addEventListener("DOMContentLoaded", function () {
    const timeline = document.querySelector(".timeline");
    const timelineEvents = timeline.querySelectorAll(".timeline__node");

    // Total animation time in seconds (same as growline duration)
    const animationDuration = 4;
    const totalEvents = timelineEvents.length;

    timelineEvents.forEach((event, index) => {
        // Calculate delay for each event based on timeline progress
        const delay = (animationDuration / totalEvents) * index;

        // Use setTimeout to add the "visible" class at the right time
        setTimeout(() => {
            event.classList.add("visible");
        }, delay * 1000); // Convert delay to milliseconds
    });
});