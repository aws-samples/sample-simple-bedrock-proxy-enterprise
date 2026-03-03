from pathlib import Path

import aws_cdk as cdk
from aws_cdk import (
    BundlingOptions,
    aws_apigateway as apigw,
    aws_bedrock as bedrock,
    aws_cognito as cognito,
    aws_iam as iam,
    aws_lambda as _lambda,
)
from constructs import Construct

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class BedrockProxyStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # --- Cognito ---
        self._user_pool, self._app_client, domain = self._create_cognito()

        # --- Application Inference Profile ---
        inference_profile = self._create_inference_profile()

        # --- Lambdas ---
        proxy_lambda = self._create_proxy_lambda()
        authorizer_lambda = self._create_authorizer_lambda(self._user_pool)

        # --- API Gateway REST with response streaming ---
        api = self._create_api(proxy_lambda, authorizer_lambda)

        # --- Outputs ---
        token_url = (
            f"https://{domain.domain_name}.auth.{self.region}"
            f".amazoncognito.com/oauth2/token"
        )
        cdk.CfnOutput(self, "ApiUrl", value=api.url)
        cdk.CfnOutput(self, "TokenUrl", value=token_url)
        cdk.CfnOutput(self, "ClientId", value=self._app_client.user_pool_client_id)
        cdk.CfnOutput(
            self,
            "InferenceProfileArn",
            value=inference_profile.attr_inference_profile_arn,
        )

    @property
    def user_pool(self) -> cognito.UserPool:
        return self._user_pool

    @property
    def app_client(self) -> cognito.UserPoolClient:
        return self._app_client

    # ------------------------------------------------------------------ #
    # Cognito
    # ------------------------------------------------------------------ #
    def _create_cognito(
        self,
    ) -> tuple[cognito.UserPool, cognito.UserPoolClient, cognito.UserPoolDomain]:
        pool = cognito.UserPool(
            self,
            "CognitoUserPool",
            user_pool_name="bedrock-proxy-sample",
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )

        # Resource server with scope for Bedrock access
        resource_server = pool.add_resource_server(
            "BedrockResourceServer",
            identifier="bedrock",
            scopes=[
                cognito.ResourceServerScope(
                    scope_name="invoke",
                    scope_description="Invoke Bedrock models",
                )
            ],
        )

        # App client with client_credentials grant
        app_client = pool.add_client(
            "ProxyAppClient",
            generate_secret=True,
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(client_credentials=True),
                scopes=[
                    cognito.OAuthScope.resource_server(
                        resource_server,
                        cognito.ResourceServerScope(
                            scope_name="invoke",
                            scope_description="Invoke Bedrock models",
                        ),
                    )
                ],
            ),
        )

        # Domain for the /oauth2/token endpoint
        domain = pool.add_domain(
            "CognitoDomain",
            cognito_domain=cognito.CognitoDomainOptions(
                domain_prefix="bedrock-proxy-sample",
            ),
        )

        return pool, app_client, domain

    # ------------------------------------------------------------------ #
    # Application Inference Profile
    # ------------------------------------------------------------------ #
    def _create_inference_profile(self) -> bedrock.CfnApplicationInferenceProfile:
        return bedrock.CfnApplicationInferenceProfile(
            self,
            "InferenceProfile",
            inference_profile_name="bedrock-proxy-sample-sonnet",
            model_source=bedrock.CfnApplicationInferenceProfile.InferenceProfileModelSourceProperty(
                copy_from=f"arn:aws:bedrock:{self.region}:{self.account}:inference-profile/us.anthropic.claude-sonnet-4-6",
            ),
        )

    # ------------------------------------------------------------------ #
    # Proxy Lambda
    # ------------------------------------------------------------------ #
    def _create_proxy_lambda(self) -> _lambda.Function:
        lwa_layer_arn = (
            f"arn:aws:lambda:{self.region}:753240598075"
            ":layer:LambdaAdapterLayerX86:25"
        )

        proxy_fn = _lambda.Function(
            self,
            "ProxyLambda",
            runtime=_lambda.Runtime.PYTHON_3_13,
            architecture=_lambda.Architecture.X86_64,
            handler="run.sh",
            code=_lambda.Code.from_asset(
                str(PROJECT_ROOT / "src" / "proxy"),
                bundling=BundlingOptions(
                    image=_lambda.Runtime.PYTHON_3_13.bundling_image,
                    platform="linux/amd64",
                    command=[
                        "bash",
                        "-c",
                        "pip install -r requirements.txt"
                        " --platform manylinux2014_x86_64"
                        " --only-binary=:all:"
                        " -t /asset-output"
                        " && cp -au . /asset-output",
                    ],
                ),
            ),
            memory_size=512,
            timeout=cdk.Duration.seconds(300),
            layers=[
                _lambda.LayerVersion.from_layer_version_arn(
                    self, "LWALayer", lwa_layer_arn
                )
            ],
            environment={
                "AWS_LAMBDA_EXEC_WRAPPER": "/opt/bootstrap",
                "AWS_LWA_INVOKE_MODE": "response_stream",
                "PORT": "8000",
                "BEDROCK_REGION": self.region,
            },
        )

        proxy_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                    "bedrock:Converse",
                    "bedrock:ConverseStream",
                ],
                resources=[
                    "arn:aws:bedrock:*::foundation-model/*",
                    f"arn:aws:bedrock:*:{self.account}:inference-profile/*",
                    f"arn:aws:bedrock:*:{self.account}:application-inference-profile/*",
                ],
            )
        )

        return proxy_fn

    # ------------------------------------------------------------------ #
    # Authorizer Lambda
    # ------------------------------------------------------------------ #
    def _create_authorizer_lambda(
        self, user_pool: cognito.UserPool
    ) -> _lambda.Function:
        return _lambda.Function(
            self,
            "AuthorizerLambda",
            runtime=_lambda.Runtime.PYTHON_3_13,
            architecture=_lambda.Architecture.X86_64,
            handler="handler.handler",
            code=_lambda.Code.from_asset(
                str(PROJECT_ROOT / "src" / "authorizer"),
                bundling=BundlingOptions(
                    image=_lambda.Runtime.PYTHON_3_13.bundling_image,
                    platform="linux/amd64",
                    command=[
                        "bash",
                        "-c",
                        "pip install -r requirements.txt"
                        " --platform manylinux2014_x86_64"
                        " --only-binary=:all:"
                        " -t /asset-output"
                        " && cp -au . /asset-output",
                    ],
                ),
            ),
            memory_size=256,
            timeout=cdk.Duration.seconds(10),
            environment={
                "USER_POOL_ID": user_pool.user_pool_id,
            },
        )

    # ------------------------------------------------------------------ #
    # API Gateway
    # ------------------------------------------------------------------ #
    def _create_api(
        self,
        proxy_lambda: _lambda.Function,
        authorizer_lambda: _lambda.Function,
    ) -> apigw.SpecRestApi:
        api_definition = self._build_api_definition(
            proxy_lambda, authorizer_lambda
        )

        api = apigw.SpecRestApi(
            self,
            "BedrockProxyApi",
            api_definition=apigw.ApiDefinition.from_inline(api_definition),
            deploy_options=apigw.StageOptions(stage_name="prod"),
            endpoint_types=[apigw.EndpointType.REGIONAL],
        )

        # Grant API Gateway permission to invoke proxy Lambda
        # arn_for_execute_api() → arn:...:api-id/*/* (matches stage/method/path)
        proxy_lambda.add_permission(
            "ProxyInvoke",
            principal=iam.ServicePrincipal("apigateway.amazonaws.com"),
            source_arn=api.arn_for_execute_api(),
        )

        # Authorizer invocations use arn:...:api-id/authorizers/*
        # which doesn't match arn_for_execute_api()'s 3-segment pattern.
        # Use a broad wildcard on the API ARN instead.
        authorizer_lambda.add_permission(
            "AuthorizerInvoke",
            principal=iam.ServicePrincipal("apigateway.amazonaws.com"),
            source_arn=cdk.Stack.of(self).format_arn(
                service="execute-api",
                resource=api.rest_api_id,
                resource_name="*",
                arn_format=cdk.ArnFormat.SLASH_RESOURCE_NAME,
            ),
        )

        return api

    def _build_api_definition(
        self,
        proxy_lambda: _lambda.Function,
        authorizer_lambda: _lambda.Function,
    ) -> dict:
        """Build OpenAPI 3.0 spec inline with streaming + auth."""
        streaming_uri = (
            f"arn:aws:apigateway:{self.region}:lambda:"
            f"path/2021-11-15/functions/{proxy_lambda.function_arn}"
            "/response-streaming-invocations"
        )
        authorizer_uri = (
            f"arn:aws:apigateway:{self.region}:lambda:"
            f"path/2015-03-31/functions/{authorizer_lambda.function_arn}"
            "/invocations"
        )

        return {
            "openapi": "3.0.1",
            "info": {"title": "Bedrock Proxy API", "version": "1.0"},
            "paths": {
                "/{proxy+}": {
                    "x-amazon-apigateway-any-method": {
                        "parameters": [
                            {
                                "name": "proxy",
                                "in": "path",
                                "required": True,
                                "schema": {"type": "string"},
                            }
                        ],
                        "security": [{"tokenAuth": []}],
                        "x-amazon-apigateway-integration": {
                            "type": "aws_proxy",
                            "httpMethod": "POST",
                            "uri": streaming_uri,
                            "responseTransferMode": "STREAM",
                            "passthroughBehavior": "when_no_match",
                        },
                    }
                }
            },
            "components": {
                "securitySchemes": {
                    "tokenAuth": {
                        "type": "apiKey",
                        "name": "x-auth-token",
                        "in": "header",
                        "x-amazon-apigateway-authtype": "custom",
                        "x-amazon-apigateway-authorizer": {
                            "type": "token",
                            "authorizerUri": authorizer_uri,
                            "authorizerResultTtlInSeconds": 300,
                            "identitySource": "method.request.header.x-auth-token",
                        },
                    }
                }
            },
        }
