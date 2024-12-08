document.addEventListener("DOMContentLoaded", function () {
    const timeline = document.querySelector("ul.timeline-list");
    const timelineEvents = timeline.querySelectorAll("li");

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