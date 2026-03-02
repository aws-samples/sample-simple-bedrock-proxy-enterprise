#!/usr/bin/env python3
import aws_cdk as cdk
from stacks.proxy_stack import BedrockProxyStack

app = cdk.App()
BedrockProxyStack(app, "BedrockProxyStack")
app.synth()
