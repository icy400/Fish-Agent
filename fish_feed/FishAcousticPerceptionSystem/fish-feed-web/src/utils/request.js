import axios from "axios";

const request = axios.create({
  baseURL: "http://192.168.0.102:8081", // 你的SpringBoot地址
  timeout: 60000,
});

export default request;
