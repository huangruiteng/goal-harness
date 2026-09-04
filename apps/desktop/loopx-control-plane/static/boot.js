const panel = document.querySelector("main");
const status = document.querySelector("#status");

window.loopxBootFailed = (message) => {
  panel.dataset.state = "error";
  status.textContent = `${message} 正在自动重试…`;
};

window.loopxBootRetrying = () => {
  panel.dataset.state = "loading";
  status.textContent = "正在重新连接本地控制面…";
};
