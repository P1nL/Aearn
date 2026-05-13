# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Structure
This repository contains a collection of AI Agent tutorials, demonstrations, and test applications. It focuses on LangGraph, ReAct Agents, FastAPI, and Model Context Protocol (MCP).

The repository is structured as a collection of standalone Python/Jupyter Notebook projects, each located in a separate directory corresponding to a specific YouTube/Bilibili tutorial video:
- `01_ReActAgentAmapMCPServerTest` - ReAct Agent integrated with Amap MCP Server
- `02_ReActAgentHILTest` - Human-in-the-Loop (HIL) with tool calls
- `03_ReActAgentMemoryTest` - Agent with short-term and long-term memory
- `04_ReActAgentHILApiTest` - Production-grade FastAPI implementation (tools, memory, HIL, error recovery)
- `05_ReActAgentHILApiMultiSessionTest` - Extended API with multi-session management and dynamic memory expiration
- `06_ReActAgentHILApiMultiSessionTaskTest` - Extended API with high-concurrency async invocation and task management
- `07_RefundApprovalAgent` - Complete e-commerce refund approval agent solution using LangChain V1.x + LangGraph V1.x + FastAPI

## General Guidelines
- As this is an educational repository with multiple independent projects, ensure you are in the correct directory when running commands or making changes to a specific project.
- Projects are primarily Python-based and use modern AI frameworks (LangGraph, LangChain, FastAPI). Look for `requirements.txt` or similar dependency files within each individual project directory rather than the repository root.
- Projects containing frontend demonstrations will have their own specific run instructions within their respective directories.
