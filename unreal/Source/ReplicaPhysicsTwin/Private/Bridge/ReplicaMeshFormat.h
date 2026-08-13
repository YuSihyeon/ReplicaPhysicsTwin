#pragma once

#include "CoreMinimal.h"

class UProceduralMeshComponent;

namespace ReplicaMeshFormat
{
/** Load the colored RPTMESH2 payload emitted by the ReplicaCAD compiler. */
bool LoadRPTMesh2(
	UProceduralMeshComponent* MeshComponent,
	const TArray<uint8>& Bytes,
	const FString& SourcePath,
	const FLinearColor& FallbackColor,
	TArray<FVector>* OutVertices = nullptr,
	TArray<FVector>* OutNormals = nullptr,
	TArray<int32>* OutTriangles = nullptr,
	TArray<FColor>* OutVertexColors = nullptr);
}
