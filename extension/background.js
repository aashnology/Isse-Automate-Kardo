// Clicking the toolbar icon opens the side panel, which stays open as you
// switch tabs -- that's the point of using a side panel over a popup.
chrome.runtime.onInstalled.addListener(() => {
  chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {});
});
