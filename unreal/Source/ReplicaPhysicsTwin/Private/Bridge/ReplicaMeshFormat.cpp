#include "Bridge/ReplicaMeshFormat.h"

#include "ProceduralMeshComponent.h"
#include "Materials/MaterialInterface.h"
#include "Materials/MaterialInstanceDynamic.h"

namespace ReplicaMeshFormat
{
bool LoadRPTMesh2(
	UProceduralMeshComponent* MeshComponent,
	const TArray<uint8>& Bytes,
	const FString& SourcePath,
	const FLinearColor& FallbackColor,
	TArray<FVector>* OutVertices,
	TArray<FVector>* OutNormals,
	TArray<int32>* OutTriangles,
	TArray<FColor>* OutVertexColors)
{
	if (MeshComponent == nullptr)
	{
		return false;
	}

	constexpr int32 HeaderBytes = 16;
	if (Bytes.Num() < HeaderBytes || FMemory::Memcmp(Bytes.GetData(), "RPTMESH2", 8) != 0)
	{
		return false;
	}

	uint32 VertexCount = 0;
	uint32 IndexCount = 0;
	FMemory::Memcpy(&VertexCount, Bytes.GetData() + 8, sizeof(uint32));
	FMemory::Memcpy(&IndexCount, Bytes.GetData() + 12, sizeof(uint32));
	const uint64 ExpectedBytes = static_cast<uint64>(HeaderBytes)
		+ static_cast<uint64>(VertexCount) * sizeof(float) * 3 * 2
		+ static_cast<uint64>(VertexCount) * sizeof(uint8) * 4
		+ static_cast<uint64>(IndexCount) * sizeof(uint32);
	if (VertexCount == 0 || IndexCount == 0 || (IndexCount % 3) != 0 || ExpectedBytes != static_cast<uint64>(Bytes.Num()))
	{
		UE_LOG(LogTemp, Error, TEXT("Invalid RPTMESH2 payload: %s vertices=%u indices=%u"), *SourcePath, VertexCount, IndexCount);
		return false;
	}

	TArray<FVector> Vertices;
	TArray<FVector> Normals;
	TArray<FColor> VertexColors;
	TArray<int32> Triangles;
	Vertices.SetNumUninitialized(static_cast<int32>(VertexCount));
	Normals.SetNumUninitialized(static_cast<int32>(VertexCount));
	VertexColors.SetNumUninitialized(static_cast<int32>(VertexCount));
	Triangles.SetNumUninitialized(static_cast<int32>(IndexCount));

	const uint8* Cursor = Bytes.GetData() + HeaderBytes;
	for (uint32 Index = 0; Index < VertexCount; ++Index)
	{
		float Values[3];
		FMemory::Memcpy(Values, Cursor, sizeof(Values));
		Cursor += sizeof(Values);
		Vertices[static_cast<int32>(Index)] = FVector(Values[0], Values[1], Values[2]);
	}
	for (uint32 Index = 0; Index < VertexCount; ++Index)
	{
		float Values[3];
		FMemory::Memcpy(Values, Cursor, sizeof(Values));
		Cursor += sizeof(Values);
		Normals[static_cast<int32>(Index)] = FVector(Values[0], Values[1], Values[2]).GetSafeNormal();
	}
	for (uint32 Index = 0; Index < VertexCount; ++Index)
	{
		uint8 RGBA[4];
		FMemory::Memcpy(RGBA, Cursor, sizeof(RGBA));
		Cursor += sizeof(RGBA);
		VertexColors[static_cast<int32>(Index)] = FColor(RGBA[0], RGBA[1], RGBA[2], RGBA[3]);
	}
	for (uint32 Index = 0; Index < IndexCount; ++Index)
	{
		uint32 VertexIndex = 0;
		FMemory::Memcpy(&VertexIndex, Cursor, sizeof(uint32));
		Cursor += sizeof(uint32);
		if (VertexIndex >= VertexCount)
		{
			UE_LOG(LogTemp, Error, TEXT("RPTMESH2 index out of range: %u >= %u"), VertexIndex, VertexCount);
			return false;
		}
		Triangles[static_cast<int32>(Index)] = static_cast<int32>(VertexIndex);
	}

	// Older RPTMESH2 files may carry zero normals.  Rebuild them from the
	// actual triangles so the real object silhouette is lit instead of flat.
	bool bNormalsReady = false;
	for (const FVector& Normal : Normals)
	{
		if (!Normal.IsNearlyZero())
		{
			bNormalsReady = true;
			break;
		}
	}
	if (!bNormalsReady)
	{
		Normals.Init(FVector::ZeroVector, Vertices.Num());
		for (uint32 Index = 0; Index + 2 < IndexCount; Index += 3)
		{
			const FVector& A = Vertices[Triangles[static_cast<int32>(Index)]];
			const FVector& B = Vertices[Triangles[static_cast<int32>(Index + 1)]];
			const FVector& C = Vertices[Triangles[static_cast<int32>(Index + 2)]];
			const FVector FaceNormal = FVector::CrossProduct(B - A, C - A);
			Normals[Triangles[static_cast<int32>(Index)]] += FaceNormal;
			Normals[Triangles[static_cast<int32>(Index + 1)]] += FaceNormal;
			Normals[Triangles[static_cast<int32>(Index + 2)]] += FaceNormal;
		}
		for (FVector& Normal : Normals)
		{
			Normal = Normal.IsNearlyZero() ? FVector::UpVector : Normal.GetSafeNormal();
		}
	}
	TArray<FVector2D> UV0;
	TArray<FProcMeshTangent> Tangents;
	MeshComponent->ClearAllMeshSections();
	MeshComponent->CreateMeshSection(0, Vertices, Triangles, Normals, UV0, VertexColors, Tangents, false);
	if (OutVertices != nullptr)
	{
		*OutVertices = Vertices;
	}
	if (OutNormals != nullptr)
	{
		*OutNormals = Normals;
	}
	if (OutTriangles != nullptr)
	{
		*OutTriangles = Triangles;
	}
	if (OutVertexColors != nullptr)
	{
		*OutVertexColors = VertexColors;
	}
	UMaterialInterface* VertexColorMaterial = LoadObject<UMaterialInterface>(
		nullptr, TEXT("/Engine/EngineDebugMaterials/VertexColorMaterial.VertexColorMaterial"));
	UMaterialInterface* BaseMaterial = LoadObject<UMaterialInterface>(
		nullptr, TEXT("/Engine/BasicShapes/BasicShapeMaterial.BasicShapeMaterial"));
	if (VertexColorMaterial != nullptr)
	{
		MeshComponent->SetMaterial(0, VertexColorMaterial);
	}
	else if (BaseMaterial != nullptr)
	{
		if (UMaterialInstanceDynamic* DynamicMaterial = UMaterialInstanceDynamic::Create(BaseMaterial, MeshComponent))
		{
			DynamicMaterial->SetVectorParameterValue(TEXT("Color"), FallbackColor);
			DynamicMaterial->SetScalarParameterValue(TEXT("Roughness"), 0.78f);
			MeshComponent->SetMaterial(0, DynamicMaterial);
		}
	}
	MeshComponent->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	MeshComponent->SetCastShadow(true);
	UE_LOG(LogTemp, Log, TEXT("Loaded ReplicaCAD RPTMESH2: %s vertices=%u triangles=%u"), *SourcePath, VertexCount, IndexCount / 3);
	return true;
}
}
