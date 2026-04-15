export default {
  server: {
    proxy: {
      "/start": {
        target: "http://localhost:7860",
        changeOrigin: true,
      },
      "/upload-voice": {
        target: "http://localhost:7860",
        changeOrigin: true,
      },
      "/clone-voice": {
        target: "http://localhost:7860",
        changeOrigin: true,
      },
      "/preview": {
        target: "http://localhost:7860",
        changeOrigin: true,
      },
      "/config": {
        target: "http://localhost:7860",
        changeOrigin: true,
      },
      "/representatives": {
        target: "http://localhost:7860",
        changeOrigin: true,
      },
    },
  },
};
