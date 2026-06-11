interface VideoResult {
  title: string;
  url: string;
  element: HTMLAnchorElement;
}

export function findPetoCoastVideos(): VideoResult[] {
  const videoElements = document.querySelectorAll<HTMLAnchorElement>('a[href*="/video/"]');
  const petoCoastVideos: VideoResult[] = [];

  videoElements.forEach((element) => {
    if (element.textContent?.toLowerCase().includes('peto coast')) {
      petoCoastVideos.push({
        title: element.textContent.trim(),
        url: element.href,
        element,
      });
    }
  });

  return petoCoastVideos;
}

export function playFirstPetoCoastVideo(): void {
  const videos = findPetoCoastVideos();
  if (videos.length > 0) {
    console.log(`Found ${videos.length} Peto Coast videos`);
    console.log(`Playing: ${videos[0].title}`);
    videos[0].element.click();
  } else {
    console.log('No Peto Coast videos found on this page');
  }
}
