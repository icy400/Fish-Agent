import axios from "axios";

const request = axios.create({
  baseURL: process.env.VUE_APP_API_BASE_URL || "http://localhost:8081",
  timeout: 60000,
});

export default request;
